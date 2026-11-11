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
    from .list_view import projection
    return {'id': key, 'code': str(record.get('fOrderCodeStr') or ''), 'execution_time': timestamp,
            'department': str(record.get('fProposedDept') or ''), 'creator': str(record.get('fCreatePerson') or ''),
            'kind': str(record.get('fOrderType') or ''), 'content': clean(record.get('fOrderContent')),
            'search_text': '\n'.join(clean(v) for v in record.values() if v is not None),
            'raw': record, 'digest': hashlib.sha256(canonical.encode()).hexdigest(), 'updated_at': now(),
            'list_ready': True, **projection(record)}

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

DETAIL_TTL_SECONDS = 3600

def merge_detail_raw(engine, notice_id, record):
    """Merge detail-query fields into notices.raw without wiping list-sync identity."""
    from sqlalchemy.orm import Session
    from .db import Notice, now
    if not isinstance(record, dict) or record.get('HEC_TechnologyOrder') not in (None, notice_id):
        if isinstance(record, dict) and record.get('HEC_TechnologyOrder') and record.get('HEC_TechnologyOrder') != notice_id:
            raise ValueError('detail_id_mismatch')
    with Session(engine) as db:
        notice = db.get(Notice, notice_id)
        if notice is None:
            raise ValueError('notice_missing')
        merged = dict(notice.raw or {})
        for key, value in (record or {}).items():
            if value is None or value == '':
                continue
            merged[key] = value
        notice.raw = merged
        if record.get('fOrderCodeStr'):
            notice.code = str(record['fOrderCodeStr'])
        if record.get('fCreatePerson'):
            notice.creator = str(record['fCreatePerson'])
        if record.get('fOrderType'):
            notice.kind = str(record['fOrderType'])
        if record.get('fProposedDept'):
            notice.department = str(record['fProposedDept'])
        if record.get('fOrderContent'):
            from html import unescape
            import re
            notice.content = unescape(re.sub(r'<[^>]+>', ' ', str(record['fOrderContent'])))
        notice.search_text = '\n'.join(str(v) for v in merged.values() if v is not None)
        from .list_view import apply_projection
        apply_projection(notice, merged)
        notice.updated_at = now()
        notice.detail_synced_at = now()
        db.commit()
    return {'merged_fields': len(record or {})}

def _line_synced_at(notice, kind):
    return getattr(notice, 'parts_synced_at' if kind == 'parts' else 'tools_synced_at', None)


def _set_line_synced_at(engine, notice_id, kind):
    from sqlalchemy.orm import Session
    from .db import Notice, now
    with Session(engine) as db:
        notice = db.get(Notice, notice_id)
        if notice is None:
            return
        stamp = now()
        if kind == 'parts':
            notice.parts_synced_at = stamp
        else:
            notice.tools_synced_at = stamp
        db.commit()
    return stamp


def _sync_line_kind(engine, notice_id, kind, fetch_line=None, force=False, ttl_seconds=DETAIL_TTL_SECONDS):
    from sqlalchemy.orm import Session
    from .db import Notice, now
    from .line_items_store import store_line_items
    from .x5 import detail as detail_source
    ready, reason = detail_source.line_template_ready(kind)
    if not ready:
        return {'status': 'skipped', 'reason': reason, 'received': 0, 'changed': 0}
    with Session(engine) as db:
        notice = db.get(Notice, notice_id)
        synced = _line_synced_at(notice, kind) if notice else None
        if (not force and synced and (now() - synced).total_seconds() < ttl_seconds):
            return {'status': 'fresh', 'synced_at': synced.isoformat() + 'Z', 'received': 0, 'changed': 0}
    try:
        fetch = fetch_line or (lambda nid: detail_source.fetch_line_items(nid, kind))
        records = fetch(notice_id)
        stored = store_line_items(engine, notice_id, kind, records or [])
        stamp = _set_line_synced_at(engine, notice_id, kind)
        return {
            'status': 'synced',
            **stored,
            'synced_at': stamp.isoformat() + 'Z' if stamp else None,
        }
    except Exception as exc:
        return {'status': 'failed', 'error_type': type(exc).__name__, 'received': 0, 'changed': 0}


def sync_detail(engine, notice_id, fetch=None, fetch_parts=None, fetch_tools=None):
    from .dispatch_store import store_dispatch
    from .x5 import detail as detail_source
    fetch = fetch or detail_source.fetch_detail
    records = fetch(notice_id)
    if not records:
        raise ValueError('detail_empty')
    # Detail action returns the master row; dispatch is a separate capture not present yet.
    merged = merge_detail_raw(engine, notice_id, records[0])
    dispatch = store_dispatch(engine, notice_id, records)
    # Parts / tooling use separate captured queries; best-effort after master merge.
    parts = _sync_line_kind(engine, notice_id, 'parts', fetch_line=fetch_parts, force=True)
    tools = _sync_line_kind(engine, notice_id, 'tools', fetch_line=fetch_tools, force=True)
    return {'notice_id': notice_id, **merged, **dispatch, 'parts': parts, 'tools': tools}

def ensure_detail(engine, notice_id, force=False, ttl_seconds=DETAIL_TTL_SECONDS, fetch=None,
                  fetch_parts=None, fetch_tools=None):
    """On-demand detail crawl when opening a notice. Skips hourly bulk; caches by detail_synced_at."""
    import hashlib
    import os
    from sqlalchemy.orm import Session
    from .db import Notice, now
    from .x5.detail import template_ready

    if os.environ.get('OA_DETAIL_ON_DEMAND', '1') in ('0', 'false', 'False'):
        return {'status': 'disabled'}
    ready, reason = template_ready()
    if not ready:
        return {'status': 'skipped', 'reason': reason}

    with Session(engine) as db:
        notice = db.get(Notice, notice_id)
        if notice is None:
            return {'status': 'missing'}

    lock_name = 'hoa_dt_' + hashlib.sha256(notice_id.encode()).hexdigest()[:20]
    with engine.connect() as conn:
        try:
            locked = conn.scalar(text('SELECT GET_LOCK(:name, 8)'), {'name': lock_name})
        except Exception:
            locked = 1
        if locked != 1:
            return {'status': 'busy'}
        try:
            with Session(engine) as db:
                notice = db.get(Notice, notice_id)
                synced = notice.detail_synced_at if notice else None
                master_fresh = bool(
                    not force and synced and (now() - synced).total_seconds() < ttl_seconds
                )
            if master_fresh:
                # Master sheet can stay cached; still backfill parts/tools if their own TTL expired.
                parts = _sync_line_kind(
                    engine, notice_id, 'parts', fetch_line=fetch_parts, force=force,
                )
                tools = _sync_line_kind(
                    engine, notice_id, 'tools', fetch_line=fetch_tools, force=force,
                )
                return {
                    'status': 'fresh',
                    'synced_at': synced.isoformat() + 'Z',
                    'parts': parts,
                    'tools': tools,
                }
            result = sync_detail(
                engine, notice_id, fetch=fetch, fetch_parts=fetch_parts, fetch_tools=fetch_tools,
            )
            return {'status': 'synced', **result}
        except Exception as exc:
            return {'status': 'failed', 'error_type': type(exc).__name__}
        finally:
            try:
                conn.execute(text('SELECT RELEASE_LOCK(:name)'), {'name': lock_name})
                conn.commit()
            except Exception:
                pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init', 'once', 'worker', 'import', 'detail'])
    parser.add_argument('--file', type=Path)
    parser.add_argument('--month')
    parser.add_argument('--id', help='技术通知单主键，用于 detail 命令')
    args = parser.parse_args()
    engine = engine_from_env()
    initialize(engine)
    if args.command == 'init':
        return
    if args.command == 'detail':
        if not args.id:
            parser.error('detail 需要 --id HEC_TechnologyOrder')
        print(json.dumps(sync_detail(engine, args.id), ensure_ascii=False))
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
