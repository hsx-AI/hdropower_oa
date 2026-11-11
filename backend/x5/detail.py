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
PARTS_ENV = 'X5_PARTS_REQUEST_PATH'
TOOLS_ENV = 'X5_TOOLS_REQUEST_PATH'
PRIVATE_DIR = Path(__file__).resolve().parents[1] / 'x5-private'

ORDER_ACTIONS = (
    'queryHEC_TechnologyOrderAction', 'orderReportDataAction',
    'queryAction', 'queryDataAction', 'loadDataAction',
)
LINE_SPECS = {
    'parts': {
        'env': PARTS_ENV,
        'default_name': 'detail-parts-request1.txt',
        'concept': 'HEC_TechnologyTechnicsAndPart',
        'actions': ('queryHEC_TechnologyTechnicsAndPartAction',),
        'id_field': 'HEC_TechnologyTechnicsAndPart',
    },
    'tools': {
        'env': TOOLS_ENV,
        'default_name': 'detail-part-process-request1.txt',
        'concept': 'HEC_TechnologyTechnicsAndPart2',
        'actions': ('queryHEC_TechnologyTechnicsAndPart2Action',),
        'id_field': 'HEC_TechnologyTechnicsAndPart2',
    },
}


class DetailRequestError(probe.ProbeError):
    pass


def detail_request_path():
    configured = os.environ.get(DETAIL_ENV)
    if configured:
        return Path(configured)
    return PRIVATE_DIR / 'detail-request1.txt'


def line_request_path(kind: str) -> Path:
    spec = LINE_SPECS[kind]
    configured = os.environ.get(spec['env'])
    if configured:
        return Path(configured)
    return PRIVATE_DIR / spec['default_name']


def _parse_curl_payload(path: Path) -> tuple[urllib.parse.SplitResult, dict]:
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
    return endpoint, payload


def read_detail_template(path: Path) -> dict:
    endpoint, payload = _parse_curl_payload(path)
    action = payload.get('action')
    concept = (payload.get('translateParameter') or {}).get('rowsConfig', {}).get('concept')
    # Captured dialog detail uses queryHEC_TechnologyOrderAction; list export uses orderReportDataAction.
    if action not in ORDER_ACTIONS:
        raise DetailRequestError(f'不支持的详情动作：{action}')
    if concept and concept != 'HEC_TechnologyOrder':
        raise DetailRequestError(f'详情数据对象不是 HEC_TechnologyOrder：{concept}')
    return {'path': endpoint.path, 'payload': payload, 'concept': concept or 'HEC_TechnologyOrder'}


def read_line_template(path: Path, kind: str) -> dict:
    spec = LINE_SPECS[kind]
    endpoint, payload = _parse_curl_payload(path)
    action = payload.get('action')
    concept = (payload.get('translateParameter') or {}).get('rowsConfig', {}).get('concept')
    if action not in spec['actions']:
        raise DetailRequestError(f'不支持的{kind}详情动作：{action}')
    if concept and concept != spec['concept']:
        raise DetailRequestError(f'{kind}数据对象不是 {spec["concept"]}：{concept}')
    return {'path': endpoint.path, 'payload': payload, 'concept': spec['concept'], 'kind': kind}


def bind_notice_filter(template: dict, notice_id: str, fallback_clause: str | None = None) -> dict:
    safe_id = str(notice_id).replace("'", "''")
    payload = copy.deepcopy(template['payload'])
    params = payload['parameters']
    original = str(params.get('filter') or '')

    def replacer(match):
        left = match.group(0).split('=', 1)[0].rstrip()
        return f"{left} = '{safe_id}'"

    patterns = [
        re.compile(r"HEC_TechnologyOrder\s*=\s*'[^']*'"),
        re.compile(r"[\w.]+\.fMasterID\s*=\s*'[^']*'"),
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
        clause = fallback_clause or f"HEC_TechnologyOrder = '{safe_id}'"
        if '{id}' in clause:
            clause = clause.format(id=safe_id)
        params['filter'] = f'({original}) AND {clause}' if original.strip() else clause
    params['offset'] = 0
    if 'limit' in params:
        params['limit'] = -1
    return {'path': template['path'], 'payload': payload}


def _query_with_template(notice_id, template, kind, config_path=None, log_root=None, overrides=None,
                         fallback_clause=None):
    config_path = Path(config_path or os.environ.get('X5_CONFIG_PATH', probe.ROOT / 'config.json'))
    config = load_config(config_path)
    output = probe.make_output_dir(
        Path(log_root or os.environ.get('X5_LOG_ROOT', probe.ROOT / 'sync_logs')), True
    )
    log = DebugLog(output)
    summary = {'mode': 'online', 'notice_id': notice_id, 'status': 'failed', 'kind': kind}
    interactive = {
        'query_timeout_seconds': int(os.environ.get('OA_DETAIL_TIMEOUT_SECONDS', '90')),
        'query_retries': int(os.environ.get('OA_DETAIL_RETRIES', '0')),
    }
    if overrides:
        interactive.update(overrides)
    try:
        bound = bind_notice_filter(template, notice_id, fallback_clause=fallback_clause)
        result, _ = probe.query_online(bound, bound['payload'], config, log, interactive)
        records = probe.extract_records(result)
        summary.update(status='query_ok', record_count=len(records))
        return records
    except BaseException as exc:
        summary['error_type'] = type(exc).__name__
        raise
    finally:
        log.finish(summary)


def fetch_detail(notice_id, config_path=None, request_path=None, log_root=None, overrides=None):
    request_path = Path(request_path or detail_request_path())
    template = read_detail_template(request_path)
    return _query_with_template(
        notice_id, template, 'detail', config_path=config_path, log_root=log_root, overrides=overrides,
    )


def fetch_line_items(notice_id, kind, config_path=None, request_path=None, log_root=None, overrides=None):
    spec = LINE_SPECS[kind]
    request_path = Path(request_path or line_request_path(kind))
    template = read_line_template(request_path, kind)
    fallback = f"{spec['concept']}.fMasterID = '{{id}}'"
    return _query_with_template(
        notice_id, template, kind, config_path=config_path, log_root=log_root, overrides=overrides,
        fallback_clause=fallback,
    )


def template_ready():
    path = detail_request_path()
    try:
        read_detail_template(path)
        return True, str(path)
    except DetailRequestError as exc:
        return False, str(exc)


def line_template_ready(kind: str):
    path = line_request_path(kind)
    try:
        read_line_template(path, kind)
        return True, str(path)
    except DetailRequestError as exc:
        return False, str(exc)
