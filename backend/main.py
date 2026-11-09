import datetime as dt
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy import select, func, desc, text
from sqlalchemy.orm import Session
from .db import Notice, Tracking, SyncRun, SyncMonth, engine_from_env

from .auth import authorize, login, logout
from .db import initialize
from .content import plain_text
from .detail_view import detail_cost, detail_header, dispatch_from_rows, parse_dispatch_records
from .dispatch_store import load_dispatch
from .sync import ensure_detail
from .admin_health import HealthMonitor

@asynccontextmanager
async def lifespan(app):
    app.state.engine = engine_from_env()
    initialize(app.state.engine)
    app.state.health_monitor = HealthMonitor()
    yield
    app.state.engine.dispose()

app = FastAPI(title='水电分厂通知单管理', lifespan=lifespan, dependencies=[Depends(authorize)])
def session():
    with Session(app.state.engine) as db:
        yield db

class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)

@app.post('/api/auth/login')
def sign_in(body: LoginInput, request: Request, response: Response, db: Session = Depends(session)):
    return login(request, response, body.username, body.password, db)

@app.get('/api/auth/me')
def me(response: Response, user=Depends(authorize)):
    response.headers['Cache-Control'] = 'no-store'
    return user

@app.post('/api/auth/logout')
def sign_out(request: Request, response: Response, db: Session = Depends(session)):
    return logout(request, response, db)

@app.get('/api/health')
def health(db: Session = Depends(session)):
    db.execute(text('SELECT 1'))
    return {'status': 'ok'}

def administrator(user=Depends(authorize)):
    if not user or user.get('role') != 'admin':
        raise HTTPException(403, '仅管理员可查看系统运维信息')
    return user

@app.get('/api/admin/health')
def admin_health(request: Request, response: Response, user=Depends(administrator)):
    response.headers['Cache-Control'] = 'no-store'
    return request.app.state.health_monitor.get(request.app.state.engine)

def view(n):
    return {'id': n.id, 'code': n.code, 'execution_time': n.execution_time.isoformat(),
            'department': n.department, 'creator': n.creator, 'kind': n.kind,
            'updated_at': n.updated_at.isoformat() + 'Z'}

def clean(value):
    return plain_text(value)

def pick(raw, *keys):
    for key in keys:
        value = raw.get(key)
        if value is None or value == '' or value == {}:
            continue
        if isinstance(value, dict) and 'value' in value:
            value = value.get('value')
        text = clean(value)
        if text:
            return text
    return ''

def flag_text(value):
    text = clean(value)
    if text in ('1', 'true', 'True', 'Y', 'y'):
        return '是'
    if text in ('0', 'false', 'False', 'N', 'n'):
        return '否'
    return text

def excerpt(value, tokens, length=320):
    value = clean(value)
    hits = [value.lower().find(t.lower()) for t in tokens if t.lower() in value.lower()]
    start = max(0, min(hits) - 75) if hits else 0
    return ('…' if start else '') + value[start:start+length] + ('…' if len(value) > start+length else '')

def listing(n, tokens, field):
    raw = n.raw or {}
    matches = [{'field': key, 'text': excerpt(value, tokens)} for key, value in raw.items()
               if (field == 'all' or key == field) and tokens
               and any(t.lower() in clean(value).lower() for t in tokens)]
    create_time = pick(raw, 'fCreateTimeStr', 'fBillTimeStr', 'fCreateTime', 'fBillTime')
    if create_time.endswith('Z') and 'T' in create_time:
        create_time = create_time.replace('T', ' ').rstrip('Z')
    return {**view(n), 'preview': excerpt(n.content, tokens),
            'work_number': pick(raw, 'fWorkPartNumStr') or clean(raw.get('fWorkPartNumStr')),
            'reason': excerpt(raw.get('fOrderCause'), tokens, 180), 'matches': matches[:6],
            'project_name': pick(raw, 'fProjectName', 'fProject', 'fName', 'fBillName', 'fClassification'),
            'issue_dept': pick(raw, 'fCreateDeptName', 'fProposedDept') or n.department,
            'create_time': create_time,
            'is_effective': flag_text(raw.get('fIsExecution')) or pick(raw, 'fIsExecution'),
            'is_discarded': flag_text(pick(raw, 'fIsAbolish', 'fAbolish', 'fIsDiscard', 'fDiscarded', 'fIsInvalid')),
            'discard_time': pick(raw, 'fAbolishTimeStr', 'fDiscardTimeStr', 'fAbolishTime', 'fDiscardTime', 'fInvalidTime')}

@app.get('/api/notices')
def notices(q: str = Query('', max_length=200), field: str = Query('all', pattern=r'^[A-Za-z_][A-Za-z0-9_]{0,63}$'),
            start: dt.date | None = None, end: dt.date | None = None,
            page: int = Query(1, ge=1, le=100000), size: int = Query(50, ge=1, le=200), db: Session = Depends(session)):
    if start and end and start > end:
        raise HTTPException(422, '开始日期不能晚于结束日期')
    conditions = []
    if start:
        conditions.append(Notice.execution_time >= dt.datetime.combine(start, dt.time()))
    if end:
        if end == dt.date.max:
            conditions.append(Notice.execution_time <= dt.datetime.max)
        else:
            conditions.append(Notice.execution_time < dt.datetime.combine(end + dt.timedelta(days=1), dt.time()))
    tokens = list(dict.fromkeys(q.split()))
    if len(tokens) > 12:
        raise HTTPException(422, '一次最多搜索12个关键词，请减少关键词后重试')
    column = Notice.search_text if field == 'all' else func.json_unquote(func.json_extract(Notice.raw, '$.' + field))
    for token in tokens:
        pattern = '%' + token.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
        conditions.append(column.like(pattern, escape='!'))
    total = db.scalar(select(func.count()).select_from(Notice).where(*conditions))
    # Read content only for this bounded page, to return snippets around matching words.
    columns = [Notice.id, Notice.code, Notice.execution_time, Notice.department, Notice.creator, Notice.kind, Notice.updated_at, Notice.content, Notice.raw]
    rows = db.execute(select(*columns).where(*conditions).order_by(desc(Notice.execution_time), Notice.id)
                      .offset((page - 1) * size).limit(size)).all()
    return {'total': total, 'page': page, 'size': size, 'items': [listing(n, tokens, field) for n in rows]}

def detail_payload(db, notice_id, sync_info=None):
    n = db.get(Notice, notice_id)
    if n is None:
        raise HTTPException(404, '通知单不存在')
    logs = db.scalars(select(Tracking).where(Tracking.notice_id == notice_id).order_by(desc(Tracking.id)).limit(200)).all()
    stored = load_dispatch(db, notice_id)
    dispatch_rows = dispatch_from_rows(stored)
    if not dispatch_rows:
        # Fall back to any nested dispatch snapshot already present on the notice raw JSON.
        dispatch_rows = [
            {k: r[k] for k in ('dept_path', 'preferred_receiver', 'receiver', 'received_at')}
            for r in parse_dispatch_records(notice_id, n.raw or {})
        ]
    header = detail_header(n)
    cost = detail_cost(n.raw or {})
    return {**view(n), 'content': plain_text((n.raw or {}).get('fOrderContent') or n.content),
            'fields': n.raw, 'detail_header': header, 'cost': cost, 'dispatch_rows': dispatch_rows,
            'dispatch_pending': len(dispatch_rows) == 0,
            'detail_sync': sync_info or {'status': 'idle'},
            'detail_synced_at': n.detail_synced_at.isoformat() + 'Z' if n.detail_synced_at else None,
            'tracking': [{'id': t.id, 'status': t.status, 'note': t.note, 'author': t.author,
                          'created_at': t.created_at.isoformat() + 'Z'} for t in logs]}

@app.get('/api/notices/{notice_id}')
def detail(notice_id: str, request: Request, refresh: bool = Query(False), db: Session = Depends(session)):
    if db.get(Notice, notice_id) is None:
        raise HTTPException(404, '通知单不存在')
    # Click-to-open crawl: one notice only, cached by detail_synced_at; not part of hourly bulk.
    sync_info = ensure_detail(request.app.state.engine, notice_id, force=refresh)
    if sync_info.get('status') == 'synced':
        db.expire_all()
    return detail_payload(db, notice_id, sync_info)

class TrackingInput(BaseModel):
    status: Literal['待处理', '处理中', '已完成']
    note: str = Field(min_length=1, max_length=2000)

@app.post('/api/notices/{notice_id}/tracking')
def track(notice_id: str, body: TrackingInput, db: Session = Depends(session), user=Depends(authorize)):
    if not db.get(Notice, notice_id):
        raise HTTPException(404, '通知单不存在')
    if not body.note.strip():
        raise HTTPException(422, '请输入跟踪说明')
    item = Tracking(notice_id=notice_id, status=body.status, note=body.note.strip(), author=user['username'])
    db.add(item)
    db.commit()
    return {'id': item.id, 'status': 'saved'}

@app.get('/api/sync/status')
def status(db: Session = Depends(session)):
    runs = db.scalars(select(SyncRun).order_by(desc(SyncRun.started_at)).limit(10)).all()
    months = db.scalars(select(SyncMonth).order_by(desc(SyncMonth.month))).all()
    return {'runs': [{'id': r.id, 'status': r.status, 'started_at': r.started_at.isoformat() + 'Z',
                      'finished_at': r.finished_at.isoformat() + 'Z' if r.finished_at else None,
                      'details': r.details} for r in runs],
            'months': [{'month': m.month, 'count': m.count, 'synced_at': m.synced_at.isoformat() + 'Z'} for m in months]}

class SPAStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith(('api/', 'assets/')) and '.' not in path:
                return await super().get_response('index.html', scope)
            raise

dist = Path(__file__).resolve().parents[1] / 'dist'
if dist.is_dir():
    app.mount('/', SPAStaticFiles(directory=dist, html=True), name='frontend')
