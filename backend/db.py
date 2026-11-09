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
    __table_args__ = (Index('ix_notice_date_id', 'execution_time', 'id'),
                      {'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'})

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
    if 'detail_synced_at' not in columns:
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE notices ADD COLUMN detail_synced_at DATETIME NULL'))
