"""Persist parts/tooling rows without wiping on a single miss."""
import hashlib
import json
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import NoticeLineItem, now
from .detail_view import parse_line_records


def row_digest(cells):
    canonical = json.dumps(cells, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()


def store_line_items(engine, notice_id, kind, records):
    rows = parse_line_records(notice_id, kind, records)
    if not rows:
        return {'received': 0, 'changed': 0}
    changed = 0
    with Session(engine) as db:
        for row in rows:
            digest = row_digest(row['cells'])
            existing = db.scalar(
                select(NoticeLineItem).where(
                    NoticeLineItem.notice_id == notice_id,
                    NoticeLineItem.kind == kind,
                    NoticeLineItem.source_key == row['source_key'],
                )
            )
            if existing and existing.digest == digest:
                continue
            if existing:
                existing.cells = row['cells']
                existing.digest = digest
                existing.updated_at = now()
            else:
                db.add(NoticeLineItem(
                    notice_id=notice_id,
                    kind=kind,
                    source_key=row['source_key'],
                    cells=row['cells'],
                    digest=digest,
                    updated_at=now(),
                ))
            changed += 1
        db.commit()
    return {'received': len(rows), 'changed': changed}


def load_line_items(db, notice_id, kind):
    return db.scalars(
        select(NoticeLineItem).where(
            NoticeLineItem.notice_id == notice_id,
            NoticeLineItem.kind == kind,
        ).order_by(NoticeLineItem.id)
    ).all()
