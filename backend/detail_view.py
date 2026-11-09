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
