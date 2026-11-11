"""Assemble the technology-order「详细内容」payload from stored notice + dispatch rows."""
from .content import plain_text


def clean(value):
    return plain_text(value)


def pick(raw, *keys):
    for key in keys:
        value = raw.get(key) if isinstance(raw, dict) else None
        if value is None or value == '' or value == {}:
            continue
        if isinstance(value, dict) and 'value' in value:
            value = value.get('value')
        text = clean(value)
        if text:
            return text
    return ''


def kind_text(raw, notice):
    styled = pick(raw, 'fOrderTypeStr')
    if styled:
        return styled
    code = pick(raw, 'fOrderTypeCode')
    label = pick(raw, 'fOrderType') or getattr(notice, 'kind', '') or ''
    if code and label and not label.startswith(code):
        return f'{code} - {label}'
    return label or code


def wall_time(value):
    text = clean(value)
    if not text:
        return ''
    # X5 often serializes wall-clock with a trailing Z; do not shift timezone.
    return text.replace('T', ' ').rstrip('Z').replace('.000', '')


def detail_header(notice):
    raw = notice.raw or {}
    return {
        'code': notice.code or pick(raw, 'fOrderCodeStr', 'fORDER_CODE', 'Sum_num'),
        'supplement_status': pick(
            raw, 'Supplementary_documents', 'fSupplementStatus', 'fIsSupplement',
            'fSupplement', 'fBjStatus', 'fReplaceStatus',
        ),
        # 发出单位 in the dialog matches company / proposed dept, not the create group.
        'issue_dept': pick(raw, 'fCreateCompany', 'fProposedDept', 'fCreateDeptName') or notice.department or '',
        'work_part': pick(raw, 'fWorkPartNumStr'),
        'reason': clean(raw.get('fOrderCause')),
        'kind': kind_text(raw, notice),
        'classification': pick(raw, 'fClassification'),
        'creator': notice.creator or pick(raw, 'fCreatePerson', 'fCreatePersonName'),
        'check_person': pick(raw, 'fCheckPerson'),
        'reviewer': pick(raw, 'fReviewer'),
        'authorized_person': pick(raw, 'fAuthorizedPerson'),
        'approval_name': pick(raw, 'fApprovalName'),
        'execution_time': (
            pick(raw, 'fExecutionTimeStr')
            or wall_time(raw.get('fExecutionTime'))
            or notice.execution_time.isoformat().replace('T', ' ')
        ),
        'create_dept': pick(raw, 'fCreateDeptName'),
        'process_state': pick(raw, 'fProcessState'),
        'giveup_state': pick(raw, 'fGiveupState'),
    }


def detail_cost(raw):
    raw = raw or {}
    return {
        'material': pick(raw, 'ON_COST', 'Expected_material_cost', 'fMaterialCost', 'fClCost', 'fMaterialFee'),
        'process': pick(raw, 'Processing_fee_estimate', 'Process_Cost', 'fProcessCost', 'fJgCost', 'fProcessFee'),
        'estimate': pick(raw, 'Estimated_cost', 'Total_estimated_cost', 'fEstimateCost', 'fYjCost', 'fExpectedCost'),
    }


def dispatch_from_rows(rows):
    return [
        {
            'dept_path': r.dept_path,
            'preferred_receiver': r.preferred_receiver,
            'receiver': r.receiver,
            'received_at': r.received_at,
        }
        for r in rows
    ]


def parse_dispatch_records(notice_id, payload):
    """Normalize possible detail/list payloads into dispatch row dicts."""
    rows = []
    if payload is None:
        return rows
    candidates = []
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        for key in (
            'dispatch', 'dispatches', 'HEC_TechnologyDispatch', 'rows',
            'fDispatchList', 'dispatchRows',
        ):
            value = payload.get(key)
            if isinstance(value, list):
                candidates = value
                break
        if not candidates and any(
            k in payload for k in ('fSelectDeptFname', 'fDeptFName', 'fPreferredPerson', 'fReceivePerson')
        ):
            candidates = [payload]
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            continue
        cell = item
        if all(isinstance(v, dict) and 'value' in v for v in item.values() if isinstance(v, dict)):
            cell = {k: (v.get('value') if isinstance(v, dict) else v) for k, v in item.items()}
        dept = pick(cell, 'fSelectDeptFname', 'fDeptFName', 'fDeptName', 'fReceiveDept', 'dept_path')
        preferred = pick(cell, 'fPreferredPerson', 'fFirstPerson', 'fSelectPerson', 'preferred_receiver')
        receiver = pick(cell, 'fReceivePerson', 'fReceiver', 'fActualPerson', 'receiver')
        received_at = pick(cell, 'fReceiveTimeStr', 'fReceiveTime', 'fReceivedAt', 'received_at')
        source_key = pick(cell, 'HEC_TechnologyDispatch', 'fDispatchID', 'id', 'source_key') or f'{notice_id}:{index}'
        if not (dept or preferred or receiver or received_at):
            continue
        rows.append({
            'notice_id': notice_id,
            'source_key': str(source_key)[:128],
            'dept_path': dept,
            'preferred_receiver': preferred,
            'receiver': receiver,
            'received_at': received_at,
        })
    return rows


PARTS_COLUMNS = (
    ('fAssemblySort', '装配序号'),
    ('fPartNumber', '零件编号'),
    ('fPartName', '零件名称'),
    ('fPartFigureNum', '零件图号'),
    ('fMaterialName', '材料名称'),
    ('fMaterialQuality', '材质'),
    ('fAmount', '数量'),
    ('fProcessNumber', '工序号'),
    ('fProcessName', '工序名称'),
    ('fRouting', '工艺路线'),
    ('fToolingNo', '工装号'),
    ('fRemarks', '备注'),
)

TOOLS_COLUMNS = (
    ('fProcessNumber', '工序号'),
    ('fProcessName', '工序名称'),
    ('fPartName', '零件名称'),
    ('fPartFigureNum', '零件图号'),
    ('fProcessToolNo', '工艺工装号'),
    ('fEquipment', '设备'),
    ('fEquipmentCode', '设备编码'),
    ('Estimated_working_hours', '预计工时'),
    ('Process_Cost', '加工费'),
    ('fRemarks', '备注'),
)

LINE_COLUMN_MAP = {'parts': PARTS_COLUMNS, 'tools': TOOLS_COLUMNS}
LINE_ID_FIELDS = {
    'parts': ('HEC_TechnologyTechnicsAndPart', 'MC_Technics_Part', 'PFE_Technics_Part'),
    'tools': ('HEC_TechnologyTechnicsAndPart2',),
}


def flatten_cell(item):
    if not isinstance(item, dict):
        return {}
    if any(isinstance(v, dict) and 'value' in v for v in item.values()):
        return {k: (v.get('value') if isinstance(v, dict) and 'value' in v else v) for k, v in item.items()}
    return item


def parse_line_records(notice_id, kind, payload):
    """Normalize parts/tools detail payloads into stored row dicts."""
    columns = LINE_COLUMN_MAP[kind]
    id_fields = LINE_ID_FIELDS[kind]
    rows = []
    if payload is None:
        return rows
    candidates = payload if isinstance(payload, list) else [payload]
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            continue
        cell = flatten_cell(item)
        source_key = pick(cell, *id_fields, 'source_key') or f'{notice_id}:{kind}:{index}'
        cells = {key: pick(cell, key) for key, _label in columns}
        if not any(cells.values()):
            # Keep sparse source rows that still carry an identity / any text field.
            extras = [clean(v) for v in cell.values() if v not in (None, '', {})]
            if not extras:
                continue
            for key in cell:
                text = pick(cell, key)
                if text and key not in cells:
                    cells[key] = text
        rows.append({
            'notice_id': notice_id,
            'kind': kind,
            'source_key': str(source_key)[:128],
            'cells': cells,
        })
    return rows


def line_columns(kind):
    return [{'key': key, 'label': label} for key, label in LINE_COLUMN_MAP[kind]]


def line_rows_from_stored(items):
    return [{'source_key': item.source_key, **(item.cells or {})} for item in items]
