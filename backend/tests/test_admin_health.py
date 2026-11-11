import datetime as dt
import json
import subprocess
from types import SimpleNamespace
from backend.tests.test_auth_search import client, sign_in
from backend import admin_health as health
from backend.db import SyncRun, SyncMonth, now
from sqlalchemy.orm import Session


def test_admin_access_enforced_before_checks(client, monkeypatch):
    calls=[]
    monkeypatch.setattr(health.HealthMonitor,'get',lambda self,engine:calls.append(1) or {'overall':'ok'})
    assert client.get('/api/admin/health').status_code==401
    sign_in(client,'reader')
    assert client.get('/api/admin/health').status_code==403
    assert calls==[]
    sign_in(client)
    r=client.get('/api/admin/health')
    assert r.status_code==200 and r.headers['cache-control']=='no-store'
    assert calls==[1]


def test_database_summary_reports_failed_sync_without_raw_logs(client):
    with Session(client.test_engine) as db:
        db.add(SyncMonth(month='2026-10',count=2,synced_at=now()))
        db.add(SyncRun(id='synthetic-run',status='partial_failure',started_at=now(),finished_at=now(),details=[
            {'month':'2026-10','status':'failed','error_type':'URLError','raw':'PRIVATE_PAYLOAD'},
            {'status':'failed','error_type':'bad token SECRET','note':'PRIVATE_PAYLOAD'}]))
        db.commit()
    result=health.database_snapshot(client.test_engine)
    assert result['status']=='ok' and result['notice_count']==2
    assert result['sync']['status']=='error'
    assert result['recent_runs'][0]['failed_months']==2
    assert result['recent_runs'][0]['error_types']=={'URLError':1}
    assert 'PRIVATE_PAYLOAD' not in json.dumps(result) and 'SECRET' not in json.dumps(result)


def test_sync_is_distinct_from_process_health():
    current=now()
    assert health.sync_summary([],current)['status']=='warning'
    recent=SimpleNamespace(status='running',started_at=current)
    assert health.sync_summary([recent],current)['status']=='running'
    recent.started_at=current-dt.timedelta(hours=3)
    assert health.sync_summary([recent],current)['status']=='warning'
    recent.status='success'
    assert health.sync_summary([recent],current)['status']=='warning'
    recent.started_at=current
    assert health.sync_summary([recent],current)['status']=='ok'


def test_systemd_fixed_units_and_timeout(monkeypatch):
    monkeypatch.setattr(health.sys,'platform','linux')
    def run(args,**kwargs):
        assert args[:2]==['systemctl','show'] and kwargs['timeout']==3
        assert 'sudo' not in args
        return SimpleNamespace(stdout='Id=hydro-oa-worker.service\nLoadState=loaded\nActiveState=active\nUnitFileState=enabled\nNRestarts=2\n\nId=nginx.service\nLoadState=loaded\nActiveState=failed\nUnitFileState=enabled\nNRestarts=0\n',returncode=0)
    monkeypatch.setattr(health.subprocess,'run',run)
    results={x['id']:x for x in health.system_services()}
    assert results['hydro-oa-worker.service']['status']=='ok'
    assert results['hydro-oa-worker.service']['enabled'] is True
    assert results['nginx.service']['status']=='error'
    assert results['mysql.service']['status']=='unknown'
    monkeypatch.setattr(health.subprocess,'run',lambda *a,**k:(_ for _ in ()).throw(subprocess.TimeoutExpired('systemctl',3)))
    assert all(s['status']=='unknown' for s in health.system_services())


def test_source_probe_only_uses_host_and_port_no_credentials(tmp_path,monkeypatch):
    path=tmp_path/'config.json'
    path.write_text(json.dumps({'base_url':'http://example.invalid:8888/path?token=SECRET','username':'PRIVATE_USER','password':'PRIVATE_PASS'}))
    monkeypatch.setenv('X5_CONFIG_PATH',str(path))
    def run(args,**kwargs):
        assert args[-2:]==['example.invalid','8888']
        assert 'SECRET' not in str(args) and 'PRIVATE_PASS' not in str(args)
        assert kwargs['timeout']==4
        return SimpleNamespace(stdout='timeout',returncode=0)
    monkeypatch.setattr(health.subprocess,'run',run)
    result=health.source_connection()
    assert result['status']=='error' and result['port']==8888
    assert 'SECRET' not in json.dumps(result)
    monkeypatch.setattr(health.subprocess,'run',lambda *a,**k:(_ for _ in ()).throw(subprocess.TimeoutExpired('probe',4)))
    assert health.source_connection()['status']=='error'


def test_monitor_cache_and_independent_statuses(monkeypatch):
    calls=[]
    monkeypatch.setattr(health,'database_snapshot',lambda engine:calls.append('db') or {'status':'ok','sync':{'status':'error'}})
    monkeypatch.setattr(health,'system_services',lambda:[{'status':'ok'}])
    monkeypatch.setattr(health,'source_connection',lambda:{'status':'ok'})
    monkeypatch.setattr(health,'detail_templates_status',lambda engine:{'status':'ok','message':'ready'})
    monitor=health.HealthMonitor()
    first=monitor.get(None)
    assert first['overall']=='error' and first['cached'] is False
    assert first['detail']['status']=='ok'
    assert monitor.get(None)['cached'] is True and calls==['db']
    monitor.expires=0
    assert monitor.get(None)['cached'] is False and calls==['db','db']


def test_detail_templates_status_reports_missing_master(tmp_path, monkeypatch, client):
    monkeypatch.setenv('X5_DETAIL_REQUEST_PATH', str(tmp_path / 'missing.txt'))
    monkeypatch.setenv('X5_PARTS_REQUEST_PATH', str(tmp_path / 'missing-parts.txt'))
    monkeypatch.setenv('X5_TOOLS_REQUEST_PATH', str(tmp_path / 'missing-tools.txt'))
    result = health.detail_templates_status(client.test_engine)
    assert result['status'] == 'error'
    assert result['master_template'] is False


def test_probe_notice_detail_uses_fetch_hooks(monkeypatch, client):
    from backend.db import Notice
    monkeypatch.setenv('OA_DETAIL_ON_DEMAND', '1')
    with Session(client.test_engine) as db:
        db.add(Notice(
            id='PROBE1', code='TZ-PROBE', execution_time=dt.datetime(2026, 11, 1),
            department='测试', creator='合成', kind='工艺', content='正文', search_text='正文',
            raw={'fOrderCodeStr': 'TZ-PROBE'}, digest='1' * 64, updated_at=now(),
        ))
        db.commit()

    monkeypatch.setattr(health, 'detail_templates_status', lambda engine: {
        'status': 'ok', 'message': 'ready', 'master_template': True, 'parts_template': True,
        'tools_template': True, 'sample_notice_id': 'PROBE1', 'sample_notice_code': 'TZ-PROBE',
    })

    class FakeDetail:
        @staticmethod
        def fetch_detail(notice_id, overrides=None):
            assert notice_id == 'PROBE1'
            assert overrides['query_timeout_seconds'] <= 60
            return [{'HEC_TechnologyOrder': 'PROBE1', 'fOrderCodeStr': 'TZ-PROBE'}]

        @staticmethod
        def fetch_line_items(notice_id, kind, overrides=None):
            return [{'id': kind}]

    import backend.x5.detail as detail_mod
    monkeypatch.setattr('backend.x5.detail.fetch_detail', FakeDetail.fetch_detail)
    monkeypatch.setattr('backend.x5.detail.fetch_line_items', FakeDetail.fetch_line_items)
    # probe imports detail inside function; patch module used via from .x5 import detail
    monkeypatch.setattr('backend.x5.detail.template_ready', lambda: (True, 'x'))
    result = health.probe_notice_detail(client.test_engine, 'PROBE1')
    assert result['status'] == 'ok'
    assert result['master']['record_count'] == 1
    assert result['parts']['record_count'] == 1
    assert result['persisted'] is False
    assert 'PRIVATE' not in json.dumps(result)

    sign_in(client)
    response = client.post('/api/admin/health/detail-probe', json={'notice_id': 'PROBE1'})
    assert response.status_code == 200
    assert response.json()['status'] == 'ok'
