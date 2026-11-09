"""Persist source distribution rows without deleting on a single miss."""
import hashlib
import json
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from .db import NoticeDispatch, now
from .detail_view import parse_dispatch_records


def row_digest(row):
    canonical = json.dumps(
        {k: row[k] for k in ('dept_path', 'preferred_receiver', 'receiver', 'received_at')},
        ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def store_dispatch(engine, notice_id, records):
    rows = parse_dispatch_records(notice_id, records)
    if not rows:
        return {'received': 0, 'changed': 0}
    changed = 0
    with engine.begin() as conn:
        for row in rows:
            payload = {**row, 'digest': row_digest(row), 'updated_at': now()}
            known = conn.execute(
                select(NoticeDispatch.digest).where(
                    NoticeDispatch.notice_id == notice_id,
                    NoticeDispatch.source_key == payload['source_key'],
                )
            ).scalar()
            if known == payload['digest']:
                continue
            stmt = insert(NoticeDispatch).values(payload)
            conn.execute(stmt.on_duplicate_key_update(
                dept_path=stmt.inserted.dept_path,
                preferred_receiver=stmt.inserted.preferred_receiver,
                receiver=stmt.inserted.receiver,
                received_at=stmt.inserted.received_at,
                digest=stmt.inserted.digest,
                updated_at=stmt.inserted.updated_at,
            ))
            changed += 1
    return {'received': len(rows), 'changed': changed}


def load_dispatch(db, notice_id):
    return db.scalars(
        select(NoticeDispatch).where(NoticeDispatch.notice_id == notice_id)
        .order_by(NoticeDispatch.id)
    ).all()
