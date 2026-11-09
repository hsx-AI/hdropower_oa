"""Detail/dispatch reader for technology orders. Requires a captured private request template."""
import copy
import json
import os
import re
import urllib.parse
from pathlib import Path
from . import probe
from .auth import load_config
from .diagnostics import DebugLog

DETAIL_ENV = 'X5_DETAIL_REQUEST_PATH'


class DetailRequestError(probe.ProbeError):
    pass


def detail_request_path():
    configured = os.environ.get(DETAIL_ENV)
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[1] / 'x5-private' / 'detail-request1.txt'


def read_detail_template(path: Path) -> dict:
    if not path.is_file():
        raise DetailRequestError(f'缺少详情请求模板：请将双击详情后的 cURL 保存为 {path}')
    text = path.read_text(encoding='utf-8-sig')
    if '^"' in text:
        text = text.replace('^', '')
    match = re.search(r'https?://[^\s"\']+', text)
    if not match or '--data-raw' not in text:
        raise DetailRequestError('详情请求不是已支持的 cURL (cmd) 格式')
    endpoint = urllib.parse.urlsplit(match.group())
    if not endpoint.path.endswith('/bizAction.j'):
        raise DetailRequestError('详情请求的接口不是 bizAction.j')
    body = text.split('--data-raw', 1)[1].strip()
    if body.startswith('"'):
        body = body[1:].replace('\\"', '"')
    elif body.startswith("'"):
        body = body[1:]
    try:
        payload, _ = json.JSONDecoder().raw_decode(body)
    except (ValueError, TypeError) as exc:
        raise DetailRequestError('不能解析详情请求的 JSON 载荷') from exc
    if not isinstance(payload.get('parameters'), dict):
        raise DetailRequestError('详情请求缺少 parameters')
    action = payload.get('action')
    concept = (payload.get('translateParameter') or {}).get('rowsConfig', {}).get('concept')
    # Captured dialog detail uses queryHEC_TechnologyOrderAction; list export uses orderReportDataAction.
    if action not in (
        'queryHEC_TechnologyOrderAction', 'orderReportDataAction', 'queryAction', 'queryDataAction', 'loadDataAction'
    ):
        raise DetailRequestError(f'不支持的详情动作：{action}')
    if concept and concept != 'HEC_TechnologyOrder':
        raise DetailRequestError(f'详情数据对象不是 HEC_TechnologyOrder：{concept}')
    return {'path': endpoint.path, 'payload': payload}


def bind_notice_filter(template: dict, notice_id: str) -> dict:
    safe_id = str(notice_id).replace("'", "''")
    payload = copy.deepcopy(template['payload'])
    params = payload['parameters']
    original = str(params.get('filter') or '')

    def replacer(match):
        left = match.group(0).split('=', 1)[0].rstrip()
        return f"{left} = '{safe_id}'"

    patterns = [
        re.compile(r"HEC_TechnologyOrder\s*=\s*'[^']*'"),
        re.compile(r"fMasterID\s*=\s*'[^']*'"),
        re.compile(r"d\.fMasterID\s*=\s*'[^']*'"),
    ]
    replaced = False
    for pattern in patterns:
        if pattern.search(original):
            params['filter'] = pattern.sub(replacer, original, count=1)
            replaced = True
            break
    if not replaced:
        clause = f"HEC_TechnologyOrder = '{safe_id}'"
        params['filter'] = f'({original}) AND {clause}' if original.strip() else clause
    params['offset'] = 0
    if 'limit' in params:
        params['limit'] = -1
    return {'path': template['path'], 'payload': payload}


def fetch_detail(notice_id, config_path=None, request_path=None, log_root=None, overrides=None):
    request_path = Path(request_path or detail_request_path())
    config_path = Path(config_path or os.environ.get('X5_CONFIG_PATH', probe.ROOT / 'config.json'))
    config = load_config(config_path)
    output = probe.make_output_dir(
        Path(log_root or os.environ.get('X5_LOG_ROOT', probe.ROOT / 'sync_logs')), True
    )
    log = DebugLog(output)
    summary = {'mode': 'online', 'notice_id': notice_id, 'status': 'failed', 'kind': 'detail'}
    # Interactive page opens should not inherit the hour-worker 900s wait by default.
    interactive = {
        'query_timeout_seconds': int(os.environ.get('OA_DETAIL_TIMEOUT_SECONDS', '90')),
        'query_retries': int(os.environ.get('OA_DETAIL_RETRIES', '0')),
    }
    if overrides:
        interactive.update(overrides)
    try:
        template = read_detail_template(request_path)
        bound = bind_notice_filter(template, notice_id)
        result, _ = probe.query_online(bound, bound['payload'], config, log, interactive)
        records = probe.extract_records(result)
        summary.update(status='query_ok', record_count=len(records))
        return records
    except BaseException as exc:
        summary['error_type'] = type(exc).__name__
        raise
    finally:
        log.finish(summary)


def template_ready():
    path = detail_request_path()
    try:
        read_detail_template(path)
        return True, str(path)
    except DetailRequestError as exc:
        return False, str(exc)
