"""Read-only operations snapshot. Fixed service allowlist; no raw logs or secrets."""
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from sqlalchemy import create_engine, select, func, text, desc
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from .db import Notice, SyncRun, SyncMonth, now

SERVICES = {'hydro-oa-api.service': 'API 服务', 'hydro-oa-worker.service': '小时同步服务',
            'nginx.service': '网页网关', 'mysql.service': 'MySQL 服务'}
CACHE_SECONDS = 30

def timestamp(value):
    return value.isoformat() + 'Z' if value else None

def system_services():
    unavailable = [{'id': unit, 'name': name, 'status': 'unknown', 'message': '当前环境无法读取系统服务状态'}
                   for unit, name in SERVICES.items()]
    if not sys.platform.startswith('linux'):
        return unavailable
    try:
        result = subprocess.run(['systemctl', 'show', *SERVICES,
            '--property=Id,LoadState,ActiveState,SubState,UnitFileState,NRestarts', '--no-pager'],
            capture_output=True, text=True, timeout=3, check=False)
        blocks = [dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
                  for block in result.stdout.strip().split('\n\n')]
        found = {block.get('Id'): block for block in blocks}
        output = []
        for unit, name in SERVICES.items():
            item = found.get(unit, {})
            state = item.get('ActiveState', 'unknown')
            loaded = item.get('LoadState') == 'loaded'
            status = ('ok' if state == 'active' else 'warning' if state in ('activating', 'deactivating')
                      else 'error' if state in ('failed', 'inactive') else 'unknown') if loaded else 'unknown'
            output.append({'id': unit, 'name': name, 'status': status,
                'state': state if state in ('active', 'inactive', 'failed', 'activating', 'deactivating') else 'unknown',
                'enabled': item.get('UnitFileState') in ('enabled', 'enabled-runtime'),
                'restarts': int(item.get('NRestarts', '0')) if item.get('NRestarts', '0').isdigit() else 0,
                'message': '服务正在运行' if status == 'ok' else '服务正在切换状态' if status == 'warning'
                           else '服务未运行，请在服务器检查' if status == 'error' else '未找到服务或无权读取状态'})
        return output
    except (OSError, subprocess.TimeoutExpired):
        return unavailable

def source_connection():
    # Configuration stays on disk; only hostname/port reach a bounded subprocess.
    try:
        path = os.environ.get('X5_CONFIG_PATH')
        if not path:
            return {'status': 'unknown', 'message': '未配置源系统连接'}
        config = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if not isinstance(config, dict):
            return {'status': 'unknown', 'message': '源系统连接配置格式不正确'}
        candidates = [config.get(key) for key in ('base_url', 'index_url', 'login_url')]
        target = next((urlsplit(value) for value in candidates if isinstance(value, str)
                       and value.startswith(('http://', 'https://'))), None)
        if not target or not target.hostname:
            return {'status': 'unknown', 'message': '源系统地址配置不完整'}
        port = target.port or (443 if target.scheme == 'https' else 80)
        code = """import socket,sys
try:
    s=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=3);s.close();print('ok')
except socket.gaierror: print('dns')
except TimeoutError: print('timeout')
except OSError: print('unreachable')
"""
        result = subprocess.run([sys.executable, '-c', code, target.hostname, str(port)],
                                capture_output=True, text=True, timeout=4, check=False)
        state = result.stdout.strip()
        messages = {'ok': '网络端口可连接；尚未验证源系统登录或查询', 'dns': '源系统域名解析失败',
                    'timeout': '源系统连接超时，请检查网络与防火墙', 'unreachable': '无法连接源系统端口'}
        return {'status': 'ok' if state == 'ok' else 'error', 'port': port,
                'message': messages.get(state, '源系统连接检查失败')}
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'message': '源系统连接检查超时（包含域名解析）'}
    except (OSError, ValueError, TypeError, StopIteration):
        return {'status': 'unknown', 'message': '无法读取源系统连接配置'}

DETAIL_PROBE_TIMEOUT_SECONDS = int(os.environ.get('OA_DETAIL_PROBE_TIMEOUT_SECONDS', '20'))


def detail_templates_status(engine):
    """Passive readiness for click-to-open detail crawl; does not call the source."""
    from .x5 import detail as detail_source
    master_ok, master_reason = detail_source.template_ready()
    parts_ok, parts_reason = detail_source.line_template_ready('parts')
    tools_ok, tools_reason = detail_source.line_template_ready('tools')
    sample_id = sample_code = None
    try:
        with Session(engine) as db:
            notice = db.scalars(select(Notice).order_by(desc(Notice.execution_time), Notice.id).limit(1)).first()
            if notice:
                sample_id, sample_code = notice.id, notice.code
    except Exception:
        pass
    if not master_ok:
        status, message = 'error', '主单详情请求模板不可用，打开通知单时无法按需爬取'
    elif not sample_id:
        status, message = 'warning', '详情模板已就绪，但库内尚无通知单可供试探'
    elif not (parts_ok and tools_ok):
        status, message = 'warning', '主单详情模板已就绪；零件/工装模板尚未齐备'
    else:
        status, message = 'ok', '详情爬取模板已就绪（主单、零件、工装）；需点下方按钮才实测源查询'
    return {
        'status': status, 'message': message,
        'master_template': master_ok, 'parts_template': parts_ok, 'tools_template': tools_ok,
        'master_reason': None if master_ok else str(master_reason)[:160],
        'parts_reason': None if parts_ok else str(parts_reason)[:160],
        'tools_reason': None if tools_ok else str(tools_reason)[:160],
        'sample_notice_id': sample_id, 'sample_notice_code': sample_code,
    }


def _probe_one(kind, fetch):
    started = time.monotonic()
    try:
        records = fetch() or []
        return {
            'status': 'ok', 'record_count': len(records),
            'latency_ms': round((time.monotonic() - started) * 1000),
        }
    except Exception as exc:
        return {
            'status': 'error', 'record_count': 0, 'error_type': type(exc).__name__,
            'latency_ms': round((time.monotonic() - started) * 1000),
        }


def probe_notice_detail(engine, notice_id=None):
    """Admin-triggered live probe: login+detail query for one notice; does not write results."""
    from .x5 import detail as detail_source

    if os.environ.get('OA_DETAIL_ON_DEMAND', '1') in ('0', 'false', 'False'):
        return {'status': 'error', 'message': '已关闭按需详情同步（OA_DETAIL_ON_DEMAND）'}

    templates = detail_templates_status(engine)
    if not templates['master_template']:
        return {
            'status': 'error', 'message': templates['message'],
            'templates': templates,
        }

    target_id = (notice_id or '').strip() or templates.get('sample_notice_id')
    if not target_id:
        return {'status': 'warning', 'message': '请填写通知单主键，或先同步至少一条通知单到库内',
                'templates': templates}

    code = None
    try:
        with Session(engine) as db:
            notice = db.get(Notice, target_id)
            if notice is None:
                return {'status': 'error', 'message': '库内找不到该通知单，请确认主键 HEC_TechnologyOrder',
                        'notice_id': target_id, 'templates': templates}
            code = notice.code
    except Exception:
        return {'status': 'error', 'message': '无法从数据库读取通知单', 'notice_id': target_id}

    timeout = max(5, min(DETAIL_PROBE_TIMEOUT_SECONDS, 60))
    overrides = {'query_timeout_seconds': timeout, 'query_retries': 0}
    started = time.monotonic()
    master = _probe_one('detail', lambda: detail_source.fetch_detail(target_id, overrides=overrides))
    parts = {'status': 'skipped', 'record_count': 0}
    tools = {'status': 'skipped', 'record_count': 0}
    if templates['parts_template']:
        parts = _probe_one(
            'parts', lambda: detail_source.fetch_line_items(target_id, 'parts', overrides=overrides),
        )
    if templates['tools_template']:
        tools = _probe_one(
            'tools', lambda: detail_source.fetch_line_items(target_id, 'tools', overrides=overrides),
        )

    statuses = [master['status'], parts['status'], tools['status']]
    if master['status'] != 'ok':
        overall = 'error'
        message = f'主单详情查询失败（{master.get("error_type") or "错误"}）'
    elif 'error' in statuses:
        overall = 'warning'
        message = '主单详情可通；零件或工装查询失败'
    elif master['record_count'] == 0:
        overall = 'warning'
        message = '已连通源详情接口，但该单主表返回 0 条'
    else:
        overall = 'ok'
        message = (
            f'详情爬取联络正常：主单 {master["record_count"]} 条，'
            f'零件 {parts.get("record_count", 0)} 条，工装 {tools.get("record_count", 0)} 条'
        )
    return {
        'status': overall, 'message': message, 'notice_id': target_id, 'notice_code': code,
        'latency_ms': round((time.monotonic() - started) * 1000),
        'timeout_seconds': timeout, 'master': master, 'parts': parts, 'tools': tools,
        'templates': templates, 'persisted': False,
    }

def sync_summary(runs, checked):
    latest = runs[0] if runs else None
    if not latest:
        return {'status': 'warning', 'message': '尚无同步记录，无法确认采集结果'}
    age = (checked - latest.started_at).total_seconds()
    if latest.status == 'running':
        return {'status': 'warning' if age > 7200 else 'running',
                'message': '本轮同步耗时较长，请检查进度' if age > 7200 else '本轮同步进行中，尚未得到最终结果'}
    if latest.status != 'success':
        return {'status': 'error', 'message': '最近一轮同步未全部成功，请查看下方记录'}
    if age > 7200:
        return {'status': 'warning', 'message': '最近同步成功，但已超过两小时没有新一轮记录'}
    return {'status': 'ok', 'message': '最近一轮同步成功'}

def database_snapshot(engine):
    checked = now()
    probe = engine
    started = time.monotonic()
    try:
        if engine.dialect.name == 'mysql':
            probe = create_engine(engine.url, poolclass=NullPool, hide_parameters=True,
                connect_args={'connect_timeout': 3, 'read_timeout': 3, 'write_timeout': 3})
        with Session(probe) as db:
            db.execute(text('SELECT 1'))
            count = db.scalar(select(func.count()).select_from(Notice))
            months, updated = db.execute(select(func.count(), func.max(SyncMonth.synced_at))).one()
            runs = db.scalars(select(SyncRun).order_by(desc(SyncRun.started_at)).limit(10)).all()
            recent = []
            for run in runs:
                details = run.details if isinstance(run.details, list) else []
                errors = {}
                for item in details:
                    if not isinstance(item, dict):
                        continue
                    kind = item.get('error_type')
                    if isinstance(kind, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', kind):
                        errors[kind] = errors.get(kind, 0) + 1
                recent.append({'id': run.id, 'status': run.status if run.status in
                    ('success', 'running', 'partial_failure', 'interrupted', 'failed') else 'unknown',
                    'started_at': timestamp(run.started_at), 'finished_at': timestamp(run.finished_at),
                    'months_processed': len(details), 'failed_months': sum(isinstance(d, dict) and d.get('status') == 'failed' for d in details),
                    'error_types': errors})
            return {'status': 'ok', 'message': '数据库连接与业务表查询正常',
                'latency_ms': round((time.monotonic() - started) * 1000),
                'notice_count': count, 'month_count': months, 'last_data_sync': timestamp(updated),
                'last_success': timestamp(db.scalar(select(func.max(SyncRun.finished_at)).where(SyncRun.status == 'success'))),
                'sync': sync_summary(runs, checked), 'recent_runs': recent}
    except Exception:
        return {'status': 'error', 'message': '数据库连接或业务表查询失败，请在服务器检查',
                'sync': {'status': 'unknown', 'message': '无法读取同步结果'}, 'recent_runs': []}
    finally:
        if probe is not engine:
            probe.dispose()

class HealthMonitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.snapshot = None
        self.expires = 0

    def get(self, engine):
        from concurrent.futures import ThreadPoolExecutor
        with self.lock:
            clock = time.monotonic()
            if self.snapshot is not None and clock < self.expires:
                return {**self.snapshot, 'cached': True, 'refresh_after_seconds': max(1, int(self.expires - clock))}
            with ThreadPoolExecutor(max_workers=4) as pool:
                database = pool.submit(database_snapshot, engine)
                services = pool.submit(system_services)
                source = pool.submit(source_connection)
                detail = pool.submit(detail_templates_status, engine)
                data, units, upstream, detail_ready = (
                    database.result(), services.result(), source.result(), detail.result(),
                )
            statuses = [
                data['status'], data['sync']['status'], upstream['status'], detail_ready['status'],
                *[s['status'] for s in units],
            ]
            overall = 'error' if 'error' in statuses else 'warning' if any(s != 'ok' for s in statuses) else 'ok'
            self.snapshot = {'checked_at': timestamp(now()), 'overall': overall,
                'api': {'status': 'ok', 'message': '管理员接口已响应，登录与权限校验通过'},
                'database': data, 'services': units, 'source': upstream, 'detail': detail_ready,
                'check_interval_seconds': CACHE_SECONDS}
            self.expires = time.monotonic() + CACHE_SECONDS
            return {**self.snapshot, 'cached': False, 'refresh_after_seconds': CACHE_SECONDS}
