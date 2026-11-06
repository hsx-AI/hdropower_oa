import { ref } from 'vue';
export const connected = ref(false);
let authorization = '';
export function setCredentials(user: string, password: string) {
  authorization = 'Basic ' + btoa(String.fromCharCode(...new TextEncoder().encode(user + ':' + password)));
}
export async function api<T>(path: string, signal?: AbortSignal, body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, { method: body ? 'POST' : 'GET', body: body ? JSON.stringify(body) : undefined, headers: { Authorization: authorization, 'Content-Type': 'application/json' }, signal });
  if (!response.ok) {
    if (response.status === 401) connected.value = false;
    throw new Error(response.status === 401 ? '请检查平台账号和密码' : `服务请求失败（${response.status}），请检查后台运行状态`);
  }
  return response.json();
}
export interface NoticeRow { id: string; code: string; execution_time: string; department: string; creator: string; kind: string; updated_at: string }
export const fields = [
  ['all', '全部字段'], ['fOrderCodeStr', '表单编号'], ['fOrderTypeCode', '类别代码'], ['fOrderType', '类别描述'],
  ['fClassification', '分类'], ['fCreateDeptName', '创建部门'], ['fCreatePerson', '创建人员'],
  ['fCheckPerson', '校核人'], ['fReviewer', '审查人'], ['fAuthorizedPerson', '审定人'],
  ['fApprovalName', '批准人'], ['fExecutionTimeStr', '生效时间'], ['fWorkPartNumStr', '工作号/部套号'],
  ['fOrderCause', '通知原因'], ['fOrderContent', '通知内容'], ['fProposedDept', '提出部门'],
] as const;
