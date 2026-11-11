import datetime as dt
import os
from sqlalchemy import create_engine, Column, String, DateTime, Text, JSON, Integer, Index, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base
from sqlalchemy.dialects.mysql import LONGTEXT

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False)
    display_name = Column(String(128), nullable=False)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(32), nullable=False, default='user')
    department = Column(String(256), nullable=False, default='')
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=lambda: now())
    last_login_at = Column(DateTime)
    __table_args__ = {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'}

class LoginSession(Base):
    __tablename__ = 'login_sessions'
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
def now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

class Notice(Base):
    __tablename__ = 'notices'
    id = Column(String(128, collation='utf8mb4_bin'), primary_key=True)
    code = Column(String(512), nullable=False)
    execution_time = Column(DateTime, nullable=False)
    department = Column(String(512), nullable=False)
    creator = Column(String(256), nullable=False)
    kind = Column(String(256), nullable=False)
    content = Column(Text().with_variant(LONGTEXT(), 'mysql'), nullable=False)
    search_text = Column(Text().with_variant(LONGTEXT(), 'mysql'), nullable=False)
    raw = Column(JSON, nullable=False)
    digest = Column(String(64), nullable=False)
    updated_at = Column(DateTime, default=now, nullable=False)
    detail_synced_at = Column(DateTime)
    parts_synced_at = Column(DateTime)
    tools_synced_at = Column(DateTime)
    # Compact columns for the list page. List queries must not read content/raw.
    reason = Column(String(800), nullable=False, default='')
    classification = Column(String(128), nullable=False, default='')
    work_number = Column(String(512), nullable=False, default='')
    discarded = Column(String(16), nullable=False, default='')
    proposed_dept = Column(String(256), nullable=False, default='')
    issue_dept = Column(String(256), nullable=False, default='')
    list_ready = Column(Boolean, nullable=False, default=False)
    __table_args__ = (
        Index('ix_notice_date_id', 'execution_time', 'id'),
        Index('ix_notice_creator', 'creator'),
        Index('ix_notice_kind', 'kind'),
        {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )

class SyncMonth(Base):
    __tablename__ = 'sync_months'
    month = Column(String(7), primary_key=True)
    count = Column(Integer, nullable=False)
    synced_at = Column(DateTime, nullable=False)

class Tracking(Base):
    __tablename__ = 'notice_tracking'
    id = Column(Integer, primary_key=True, autoincrement=True)
    notice_id = Column(String(128, collation='utf8mb4_bin'), nullable=False, index=True)
    status = Column(String(32), nullable=False)
    note = Column(Text, nullable=False)
    author = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=now, nullable=False)
    __table_args__ = {'mysql_charset': 'utf8mb4'}

class NoticeDispatch(Base):
    """Source distribution rows; never overwritten by platform tracking."""
    __tablename__ = 'notice_dispatch'
    id = Column(Integer, primary_key=True, autoincrement=True)
    notice_id = Column(String(128, collation='utf8mb4_bin'), nullable=False, index=True)
    source_key = Column(String(128, collation='utf8mb4_bin'), nullable=False, default='')
    dept_path = Column(String(1024), nullable=False, default='')
    preferred_receiver = Column(String(256), nullable=False, default='')
    receiver = Column(String(256), nullable=False, default='')
    received_at = Column(String(64), nullable=False, default='')
    digest = Column(String(64), nullable=False, default='')
    updated_at = Column(DateTime, default=now, nullable=False)
    __table_args__ = (Index('ux_notice_dispatch_key', 'notice_id', 'source_key', unique=True),
                      {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'})

class NoticeLineItem(Base):
    """Parts/process and tooling rows from on-demand detail queries."""
    __tablename__ = 'notice_line_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    notice_id = Column(String(128, collation='utf8mb4_bin'), nullable=False, index=True)
    kind = Column(String(16), nullable=False, default='parts')
    source_key = Column(String(128, collation='utf8mb4_bin'), nullable=False, default='')
    cells = Column(JSON, nullable=False)
    digest = Column(String(64), nullable=False, default='')
    updated_at = Column(DateTime, default=now, nullable=False)
    __table_args__ = (Index('ux_notice_line_key', 'notice_id', 'kind', 'source_key', unique=True),
                      {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'})

class SyncRun(Base):
    __tablename__ = 'sync_runs'
    id = Column(String(36), primary_key=True)
    started_at = Column(DateTime, default=now, nullable=False, index=True)
    finished_at = Column(DateTime)
    status = Column(String(32), nullable=False)
    details = Column(JSON, nullable=False)

def engine_from_env():
    url = os.environ.get('DATABASE_URL')
    if not url or not url.startswith('mysql+pymysql://'):
        raise RuntimeError('请配置 DATABASE_URL=mysql+pymysql://…/hydro_oa?charset=utf8mb4')
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800, pool_size=5, max_overflow=5,
                         hide_parameters=True, connect_args={'connect_timeout': 15})

def initialize(engine):
    Base.metadata.create_all(engine)
    # create_all does not ALTER existing tables; add on-demand detail cache column when missing.
    from sqlalchemy import inspect, text
    try:
        columns = {column['name'] for column in inspect(engine).get_columns('notices')}
    except Exception:
        return
    alters = []
    if 'detail_synced_at' not in columns:
        alters.append('ADD COLUMN detail_synced_at DATETIME NULL')
    if 'parts_synced_at' not in columns:
        alters.append('ADD COLUMN parts_synced_at DATETIME NULL')
    if 'tools_synced_at' not in columns:
        alters.append('ADD COLUMN tools_synced_at DATETIME NULL')
    if 'reason' not in columns:
        alters.append("ADD COLUMN reason VARCHAR(800) NOT NULL DEFAULT ''")
    if 'classification' not in columns:
        alters.append("ADD COLUMN classification VARCHAR(128) NOT NULL DEFAULT ''")
    if 'work_number' not in columns:
        alters.append("ADD COLUMN work_number VARCHAR(512) NOT NULL DEFAULT ''")
    if 'discarded' not in columns:
        alters.append("ADD COLUMN discarded VARCHAR(16) NOT NULL DEFAULT ''")
    if 'proposed_dept' not in columns:
        alters.append("ADD COLUMN proposed_dept VARCHAR(256) NOT NULL DEFAULT ''")
    if 'issue_dept' not in columns:
        alters.append("ADD COLUMN issue_dept VARCHAR(256) NOT NULL DEFAULT ''")
    if 'list_ready' not in columns:
        alters.append('ADD COLUMN list_ready TINYINT(1) NOT NULL DEFAULT 0')
    if alters:
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE notices ' + ', '.join(alters)))
    try:
        existing = {index['name'] for index in inspect(engine).get_indexes('notices')}
    except Exception:
        return
    index_sql = []
    if 'ix_notice_creator' not in existing:
        index_sql.append('CREATE INDEX ix_notice_creator ON notices (creator)')
    if 'ix_notice_kind' not in existing:
        index_sql.append('CREATE INDEX ix_notice_kind ON notices (kind)')
    if index_sql:
        with engine.begin() as conn:
            for statement in index_sql:
                conn.execute(text(statement))
