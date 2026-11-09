import datetime as dt
from types import SimpleNamespace
from pathlib import Path
import pytest
from backend.detail_view import detail_header, detail_cost, parse_dispatch_records
from backend.x5.detail import read_detail_template, bind_notice_filter, DetailRequestError


def notice_obj(**raw_extra):
    raw = {
        'fOrderCodeStr': 'TZ-A', 'fCreateDeptName': '智能制造工艺部', 'fProposedDept': '提出部',
        'Supplementary_documents': '非补件', 'fWorkPartNumStr': '002293-2/VGG20///',
        'fOrderCause': '根据工地反馈补供薄螺母', 'fOrderTypeCode': 'J', 'fOrderType': '转发其他单位通知单',
        'fOrderTypeStr': 'J - 转发其他单位通知单', 'fCreateCompany': '智能制造工艺部',
        'fClassification': '水轮发电机', 'ON_COST': '0.28', 'Processing_fee_estimate': '0', 'Estimated_cost': '0.28',
        'fOrderContent': '正文', 'fCreatePerson': '张三', **raw_extra,
    }
    return SimpleNamespace(
        id='A', code='TZ-A', department='提出部', creator='张三', kind='转发其他单位通知单',
        execution_time=dt.datetime(2026, 11, 9, 11, 4, 44), raw=raw, content='正文',
    )


def test_detail_header_and_cost_mapping():
    n = notice_obj()
    header = detail_header(n)
    assert header['code'] == 'TZ-A'
    assert header['supplement_status'] == '非补件'
    assert header['issue_dept'] == '智能制造工艺部'
    assert header['kind'] == 'J - 转发其他单位通知单'
    assert detail_cost(n.raw) == {'material': '0.28', 'process': '0', 'estimate': '0.28'}


def test_parse_dispatch_records():
    rows = parse_dispatch_records('A', [
        {'HEC_TechnologyDispatch': 'D1', 'fSelectDeptFname': '/成品分厂/计划调度组',
         'fPreferredPerson': '杨涛', 'fReceivePerson': '杨涛', 'fReceiveTimeStr': '2026-11-09 12:00:00'},
    ])
    assert len(rows) == 1
    assert rows[0]['preferred_receiver'] == '杨涛'
    assert rows[0]['source_key'] == 'D1'


def test_ensure_detail_on_demand_cache(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from backend.db import Base, Notice, initialize, now
    from backend import sync as sync_mod
    import datetime as dt

    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)

    @event.listens_for(engine, 'connect')
    def collations(conn, _):
        conn.create_collation('utf8mb4_bin', lambda a, b: (a > b) - (a < b))

    initialize(engine)
    with Session(engine) as db:
        db.add(Notice(
            id='A', code='TZ-A', execution_time=dt.datetime(2026, 10, 1), department='测试部门',
            creator='合成', kind='工艺', content='正文', search_text='正文', raw={'fOrderCodeStr': 'TZ-A'},
            digest='0' * 64, updated_at=now(),
        ))
        db.commit()

    monkeypatch.setattr('backend.x5.detail.template_ready', lambda: (True, str(tmp_path)))
    calls = {'n': 0}

    def fetch(_id):
        calls['n'] += 1
        return [{'HEC_TechnologyOrder': 'A', 'fOrderCodeStr': 'TZ-A', 'Supplementary_documents': '非补件',
                 'fCreateCompany': '智能制造工艺部', 'fOrderTypeStr': 'J - 转发', 'Estimated_cost': '1'}]

    first = sync_mod.ensure_detail(engine, 'A', fetch=fetch)
    second = sync_mod.ensure_detail(engine, 'A', fetch=fetch)
    forced = sync_mod.ensure_detail(engine, 'A', force=True, fetch=fetch)
    assert first['status'] == 'synced' and second['status'] == 'fresh' and forced['status'] == 'synced'
    assert calls['n'] == 2
    with Session(engine) as db:
        assert db.get(Notice, 'A').detail_synced_at is not None
        assert db.get(Notice, 'A').raw.get('Supplementary_documents') == '非补件'


def test_detail_template_bind(tmp_path):
    curl = (
        'curl "http://capture.invalid/x5/UI2/v_test/system/service/common/bizAction.j" '
        '--data-raw "{\\"action\\":\\"orderReportDataAction\\",\\"process\\":\\"p\\",\\"activity\\":\\"a\\",'
        '\\"parameters\\":{\\"filter\\":\\"HEC_TechnologyOrder = \'OLD\'\\",\\"offset\\":0,\\"limit\\":20}}"'
    )
    path = tmp_path / 'detail-request1.txt'
    path.write_text(curl, encoding='utf-8')
    template = read_detail_template(path)
    bound = bind_notice_filter(template, "ABC'1")
    assert "HEC_TechnologyOrder = 'ABC''1'" in bound['payload']['parameters']['filter']
    with pytest.raises(DetailRequestError):
        read_detail_template(tmp_path / 'missing.txt')
