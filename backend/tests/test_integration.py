import datetime as dt
import os
import uuid
import pytest
from sqlalchemy import create_engine, text, select
from fastapi.testclient import TestClient
from backend.db import initialize, Notice, User
from backend.auth import hash_password
from sqlalchemy.orm import Session
from backend.sync import store_month, cycle, normalize

def test_x5_wall_clock_month_end():
    r = record()
    r.update(fExecutionTime='2026-10-31T18:13:56.000Z', fExecutionTimeStr='2026-10-31 18:13:56')
    assert normalize(r)['execution_time'] == dt.datetime(2026,10,31,18,13,56)
from backend.main import app

@pytest.fixture
def database(monkeypatch):
    base = os.environ.get('TEST_MYSQL_URL')
    if not base:
        pytest.skip('需要独立测试MySQL的 TEST_MYSQL_URL')
    admin = create_engine(base)
    name = 'hydro_test_' + uuid.uuid4().hex
    with admin.begin() as conn:
        conn.execute(text(f'CREATE DATABASE `{name}` CHARACTER SET utf8mb4'))
    url = admin.url.set(database=name)
    engine = create_engine(url, hide_parameters=True)
    initialize(engine)
    with Session(engine) as db:
        db.add(User(username='test',display_name='测试员',role='admin',password_hash=hash_password('test-password')))
        db.commit()
    monkeypatch.setenv('DATABASE_URL', url.render_as_string(hide_password=False))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP DATABASE `{name}`'))
        admin.dispose()

def record(key='A', content='水电 转轮 100%_设备'):
    return {'HEC_TechnologyOrder': key, 'fExecutionTime': '2026-10-01T01:00:00',
            'fOrderCodeStr': '通知-' + key, 'fOrderContent': content, 'fCreatePerson': '测试员'}

def test_upsert_and_atomic_validation(database):
    assert store_month(database, '2026-10', [record()])['changed'] == 1
    assert store_month(database, '2026-10', [record()])['changed'] == 0
    assert store_month(database, '2026-10', [record(content='已修改')])['changed'] == 1
    with pytest.raises(ValueError):
        store_month(database, '2026-10', [])
    with pytest.raises(ValueError):
        store_month(database, '2026-10', [record(), record()])
    with database.connect() as conn:
        assert conn.scalar(select(Notice.content)) == '已修改'

def test_api_search_pagination_auth_detail(database):
    store_month(database, '2026-10', [record(), record('B', '<script>alert(1)</script>不同内容')])
    with TestClient(app) as client:
        assert client.get('/api/notices').status_code == 401
        assert client.post('/api/auth/login', json={'username':'test','password':'test-password'}).status_code == 200
        assert client.get('/api/notices?q=100%25_').json()['total'] == 1
        assert client.get('/api/notices?q=测试员&field=fCreatePerson').json()['total'] == 2
        assert client.get('/api/notices?size=1&page=2').json()['items'][0]['id'] == 'B'
        assert client.get('/api/notices?start=2026-11-01').json()['total'] == 0
        assert client.get('/api/notices/A').json()['fields']['HEC_TechnologyOrder'] == 'A'
        assert client.get('/api/notices/missing').status_code == 404
        assert client.get('/api/notices?size=10000').status_code == 422
        assert client.get('/api/notices?field=x%22').status_code == 422
        assert client.get('/api/notices?start=2026-11-01&end=2026-10-01').status_code == 422

def test_cycle_resume_lock_and_partial_failure(database):
    result = cycle(database, fetch=lambda month: [record()], months=['2026-10'])
    assert result['status'] == 'success'
    result = cycle(database, fetch=lambda month: pytest.fail('should skip recently synced'), months=['2026-10'])
    assert result['details'][0]['status'] == 'recently_synced'
    result = cycle(database, fetch=lambda month: (_ for _ in ()).throw(TimeoutError()), months=['2026-09'])
    assert result['status'] == 'partial_failure'
    with database.connect() as conn:
        assert conn.scalar(text("SELECT GET_LOCK('hydro_oa_x5_sync',0)")) == 1
        assert cycle(database, months=['2026-10'])['status'] == 'already_running'
        conn.execute(text("SELECT RELEASE_LOCK('hydro_oa_x5_sync')"))
