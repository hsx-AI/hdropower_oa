import datetime as dt
import os
from sqlalchemy import create_engine, Column, String, DateTime, Text, JSON, Integer, Index
from sqlalchemy.orm import declarative_base
from sqlalchemy.dialects.mysql import LONGTEXT

Base = declarative_base()
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
