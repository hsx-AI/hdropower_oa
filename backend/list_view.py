"""Compact list columns so browsing does not read notice body or raw JSON."""
import threading
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from .content import plain_text
from .detail_view import pick
from .db import Notice


def clip(value, limit):
    return plain_text(value)[:limit]


def flag(value):
    text = plain_text(value)
    if text in ('1', 'true', 'True', 'Y', 'y', '是', '废弃', '已废弃'):
        return '是'
    if text in ('0', 'false', 'False', 'N', 'n', '否', '正常', '未废弃'):
        return '否'
    return text[:16]


def projection(raw):
    raw = raw or {}
    return {
        'reason': clip(raw.get('fOrderCause'), 800),
        'classification': clip(pick(raw, 'fClassification'), 128),
        'work_number': clip(pick(raw, 'fWorkPartNumStr', 'fWorkNumber'), 512),
        'discarded': flag(pick(raw, 'fGiveupState', 'fIsAbolish', 'fAbolish', 'fIsDiscard', 'fDiscarded', 'fIsInvalid')),
        'proposed_dept': clip(pick(raw, 'fProposedDept'), 256),
        'issue_dept': clip(pick(raw, 'fCreateCompany', 'fCreateDeptName', 'fProposedDept'), 256),
    }


def apply_projection(notice, raw):
    for key, value in projection(raw).items():
        setattr(notice, key, value)
    notice.list_ready = True


def hydrate_page(db, ids):
    """Fill list columns for the current page only, until the background backfill finishes."""
    if not ids:
        return
    rows = db.scalars(select(Notice).where(Notice.id.in_(ids), Notice.list_ready.is_(False))).all()
    if not rows:
        return
    for notice in rows:
        apply_projection(notice, notice.raw or {})
    db.commit()


def backfill_list_columns(engine, batch=200):
    while True:
        with Session(engine) as db:
            rows = db.scalars(select(Notice).where(Notice.list_ready.is_(False)).limit(batch)).all()
            if not rows:
                return
            for notice in rows:
                apply_projection(notice, notice.raw or {})
            db.commit()


def ensure_search_index(engine):
    """Chinese full-text index so keyword search does not scan the whole body."""
    if engine.dialect.name != 'mysql':
        return False
    try:
        with engine.connect() as conn:
            found = conn.execute(text(
                "SHOW INDEX FROM notices WHERE Key_name = 'ft_notice_search'"
            )).first()
            if found:
                return True
        with engine.begin() as conn:
            conn.execute(text(
                'ALTER TABLE notices ADD FULLTEXT INDEX ft_notice_search (search_text) WITH PARSER ngram'
            ))
        _fts_cache['ready'] = True
        _fts_cache['checked'] = __import__('time').monotonic()
        return True
    except Exception:
        return False


_fts_cache = {'ready': None, 'checked': 0.0}


def search_index_ready(engine):
    import time
    if engine.dialect.name != 'mysql':
        return False
    clock = time.monotonic()
    if _fts_cache['ready'] is not None and clock - _fts_cache['checked'] < 30:
        return _fts_cache['ready']
    try:
        with engine.connect() as conn:
            ready = conn.execute(text(
                "SHOW INDEX FROM notices WHERE Key_name = 'ft_notice_search'"
            )).first() is not None
    except Exception:
        ready = False
    _fts_cache['ready'] = ready
    _fts_cache['checked'] = clock
    return ready


def prepare_list_speed(engine):
    try:
        backfill_list_columns(engine)
        ensure_search_index(engine)
    except Exception:
        return


def start_list_prepare(engine):
    if engine.dialect.name != 'mysql':
        return
    threading.Thread(target=prepare_list_speed, args=(engine,), name='notice-list-prepare', daemon=True).start()
