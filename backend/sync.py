"""Single-writer, transactional month reconciliation. Never deletes source records."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
import uuid
from sqlalchemy import select, text, func
from sqlalchemy.dialects.mysql import insert
from .db import Notice, SyncMonth, SyncRun, engine_from_env, initialize, now

def crawler():
    from .x5 import sync as source
    return source

def normalize(record):
    from html import unescape
    import re
    def clean(value):
        return unescape(re.sub(r'<[^>]+>', ' ', str(value or '')))
    key = record.get('HEC_TechnologyOrder')
    if not isinstance(key, str) or not key or len(key) > 128:
        raise ValueError('invalid_source_id')
    # X5 serializes its business wall-clock with Z; the captured display field confirms
    # that it is NOT an instruction to add eight hours. Preserve source filter semantics.
    timestamp = dt.datetime.fromisoformat(str(record['fExecutionTime']).replace('Z', '+00:00')).replace(tzinfo=None)
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return {'id': key, 'code': str(record.get('fOrderCodeStr') or ''), 'execution_time': timestamp,
            'department': str(record.get('fProposedDept') or ''), 'creator': str(record.get('fCreatePerson') or ''),
            'kind': str(record.get('fOrderType') or ''), 'content': clean(record.get('fOrderContent')),
            'search_text': '\n'.join(clean(v) for v in record.values() if v is not None),
            'raw': record, 'digest': hashlib.sha256(canonical.encode()).hexdigest(), 'updated_at': now()}

def store_month(engine, month, records):
    rows = [normalize(r) for r in records]
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('duplicate_source_id')
    if any(r['execution_time'].strftime('%Y-%m') != month for r in rows):
        raise ValueError('out_of_month')
    start = dt.datetime.fromisoformat(month + '-01')
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    changed = 0
    with engine.begin() as conn:
        prior = conn.scalar(select(func.count()).select_from(Notice).where(Notice.execution_time >= start, Notice.execution_time < end))
        if len(rows) < prior:
            raise ValueError('source_count_decreased_requires_review')
        for offset in range(0, len(rows), 200):
            batch = rows[offset:offset + 200]
            known = dict(conn.execute(select(Notice.id, Notice.digest).where(Notice.id.in_([r['id'] for r in batch]))).all())
            updates = [r for r in batch if known.get(r['id']) != r['digest']]
            if updates:
                stmt = insert(Notice).values(updates)
                conn.execute(stmt.on_duplicate_key_update(**{c: getattr(stmt.inserted, c) for c in updates[0] if c != 'id'}))
                changed += len(updates)
        stmt = insert(SyncMonth).values(month=month, count=len(rows), synced_at=now())
        conn.execute(stmt.on_duplicate_key_update(count=len(rows), synced_at=now()))
    return {'month': month, 'received': len(rows), 'changed': changed, 'unchanged': len(rows) - changed}

def cycle(engine, fetch=None, months=None):
    source = crawler()
    months = months or source.months_since(3)
    fetch = fetch or source.fetch_month
    run_id = str(uuid.uuid4())
    with engine.connect() as lock:
        if lock.scalar(text("SELECT GET_LOCK('hydro_oa_x5_sync', 0)")) != 1:
            return {'status': 'already_running'}
        details = []
        try:
            with engine.begin() as conn:
                conn.execute(SyncRun.__table__.update().where(SyncRun.status == 'running').values(status='interrupted', finished_at=now()))
                conn.execute(insert(SyncRun).values(id=run_id, status='running', details=[]))
            for month in months:
                if lock.scalar(text("SELECT IS_USED_LOCK('hydro_oa_x5_sync') = CONNECTION_ID()")) != 1:
                    raise RuntimeError('sync_lock_lost')
                with engine.connect() as conn:
                    synced = conn.scalar(select(SyncMonth.synced_at).where(SyncMonth.month == month))
                if synced and (now() - synced).total_seconds() < 3500:
                    details.append({'month': month, 'status': 'recently_synced'})
                    continue
                try:
                    result = store_month(engine, month, fetch(month))
                    details.append({**result, 'status': 'ok'})
                except Exception as exc:
                    details.append({'month': month, 'status': 'failed', 'error_type': type(exc).__name__,
                                    'reason': str(exc) if isinstance(exc, ValueError) and str(exc) in
                                    ('source_count_decreased_requires_review', 'duplicate_source_id', 'out_of_month', 'invalid_source_id') else 'see_x5_diagnostics'})
                with engine.begin() as conn:
                    conn.execute(SyncRun.__table__.update().where(SyncRun.id == run_id).values(details=list(details)))
            status = 'partial_failure' if any(d['status'] == 'failed' for d in details) else 'success'
            return {'status': status, 'details': details}
        except BaseException:
            status = 'interrupted'
            raise
        finally:
            with engine.begin() as conn:
                conn.execute(SyncRun.__table__.update().where(SyncRun.id == run_id).values(
                    status=locals().get('status', 'failed'), details=details, finished_at=now()))
            lock.execute(text("SELECT RELEASE_LOCK('hydro_oa_x5_sync')"))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init', 'once', 'worker', 'import'])
    parser.add_argument('--file', type=Path)
    parser.add_argument('--month')
    args = parser.parse_args()
    engine = engine_from_env()
    initialize(engine)
    if args.command == 'init':
        return
    if args.command == 'import':
        if not args.file or not args.month:
            parser.error('import需要 --file records.json --month YYYY-MM')
        # Use the same lock as the scheduled writer.
        with engine.connect() as conn:
            if conn.scalar(text("SELECT GET_LOCK('hydro_oa_x5_sync', 0)")) != 1:
                raise RuntimeError('sync_already_running')
            try:
                print(json.dumps(store_month(engine, args.month, json.loads(args.file.read_text(encoding='utf-8-sig')))))
            finally:
                conn.execute(text("SELECT RELEASE_LOCK('hydro_oa_x5_sync')"))
        return
    while True:
        started = time.monotonic()
        try:
            result = cycle(engine)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if args.command == 'once' and result['status'] not in ('success', 'already_running'):
                raise SystemExit(1)
        except Exception as exc:
            print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}), flush=True)
            if args.command == 'once':
                raise SystemExit(1)
        if args.command == 'once':
            return
        time.sleep(max(1, 3600 - (time.monotonic() - started)))

if __name__ == '__main__':
    main()
