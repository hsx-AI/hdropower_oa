import datetime as dt
import hashlib
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from backend import main
from backend.auth import hash_password, verify_password, _attempts
from backend.db import Base, User, LoginSession, Notice, Tracking, now
from backend.content import plain_text

@pytest.fixture
def client(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    @event.listens_for(engine, 'connect')
    def collations(conn, _):
        conn.create_collation('utf8mb4_bin', lambda a,b: (a>b)-(a<b))
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([User(username='admin',display_name='测试管理员',role='admin',password_hash=hash_password('synthetic-password')),
                    User(username='reader',display_name='测试用户',role='user',password_hash=hash_password('synthetic-password'))])
        for key,content in [('A','转轮 安装前必须检查尺寸 100%_设备'),('B','另一张水泵通知')]:
            db.add(Notice(id=key,code='TZ-'+key,execution_time=dt.datetime(2026,10,1),department='测试部门',creator='合成人员',kind='工艺',content=content,search_text=content+' 测试部门',raw={'fOrderContent':content,'fOrderCodeStr':'TZ-'+key},digest='0'*64))
        db.commit()
    monkeypatch.setattr(main,'engine_from_env',lambda:engine)
    _attempts.clear()
    with TestClient(main.app) as c:
        c.test_engine=engine
        yield c

def sign_in(client, username='admin'):
    return client.post('/api/auth/login',json={'username':username,'password':'synthetic-password'})

def test_auth_lifecycle_and_cookie(client):
    assert client.get('/api/notices').status_code==401
    assert client.get('/api/sync/status').status_code==401
    assert client.get('/api/notices',auth=('admin','synthetic-password')).status_code==401
    result=sign_in(client)
    assert result.status_code==200 and result.json()['role']=='admin'
    assert 'password_hash' not in result.json()
    assert 'HttpOnly' in result.headers['set-cookie'] and 'SameSite=strict' in result.headers['set-cookie']
    assert client.get('/api/auth/me').json()['username']=='admin'
    token=client.cookies.get('oa_session')
    with Session(client.test_engine) as db:
        assert db.get(LoginSession,hashlib.sha256(token.encode()).hexdigest())
        assert db.get(LoginSession,token) is None
    assert client.post('/api/auth/logout',json={}).status_code==200
    client.cookies.set('oa_session',token)
    assert client.get('/api/notices').status_code==401

def test_bad_login_origin_and_rate_limit(client):
    assert client.post('/api/auth/login',headers={'Origin':'https://untrusted.invalid'},json={'username':'admin','password':'synthetic-password'}).status_code==403
    for _ in range(20):
        assert client.post('/api/auth/login',json={'username':'missing','password':'bad'}).status_code==401
    assert sign_in(client).status_code==429

def test_disabled_expired_and_csrf(client):
    sign_in(client)
    assert client.post('/api/notices/A/tracking',headers={'Origin':'https://untrusted.invalid'},json={'status':'处理中','note':'合成记录'}).status_code==403
    with Session(client.test_engine) as db:
        session=db.scalar(select(LoginSession));session.expires_at=now()-dt.timedelta(seconds=1);db.commit()
    assert client.get('/api/auth/me').status_code==401
    sign_in(client)
    with Session(client.test_engine) as db:
        user=db.scalar(select(User).where(User.username=='admin'));user.active=False;db.commit()
    assert client.get('/api/auth/me').status_code==401

def test_search_tokens_literal_wildcards_and_tracking_author(client):
    sign_in(client,'reader')
    result=client.get('/api/notices',params={'q':'尺寸 转轮'}).json()
    assert result['total']==1 and result['items'][0]['id']=='A'
    assert '尺寸' in result['items'][0]['preview']
    assert result['items'][0]['matches'][0]['field']=='fOrderContent'
    assert client.get('/api/notices',params={'q':'100%_'}).json()['total']==1
    assert client.get('/api/notices',params={'q':'转轮 不存在'}).json()['total']==0
    assert client.get('/api/notices',params={'q':' '.join(str(i) for i in range(13))}).status_code==422
    assert client.post('/api/notices/A/tracking',json={'status':'处理中','note':'合成测试记录'}).status_code==200
    with Session(client.test_engine) as db:
        assert db.scalar(select(Tracking.author))=='reader'

def test_password_and_plain_text():
    hashed=hash_password('synthetic-password')
    assert hashed!='synthetic-password' and verify_password('synthetic-password',hashed)
    assert not verify_password('wrong',hashed)
    assert plain_text('<p>第一段</p><p>第二段<br>第三行</p><script>secret</script>')=='第一段\n第二段\n第三行'
