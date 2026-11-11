import { ref } from 'vue';
export interface User {
  id: number;
  username: string;
  display_name: string;
  role: string;
  department: string;
}
export const currentUser = ref<User | null>(null);
export const connected = ref(false);
export async function api<T>(path: string, signal?: AbortSignal, body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, {
    credentials: 'same-origin',
    method: body !== undefined ? 'POST' : 'GET',
    body: body !== undefined ? JSON.stringify(body) : undefined,
    headers: { 'Content-Type': 'application/json' },
    signal,
  });
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login') {
      currentUser.value = null;
      connected.value = false;
      const target = location.hash.slice(1);
      if (!target.startsWith('/login'))
        location.hash = '/login?redirect=' + encodeURIComponent(target || '/notices');
    }
    const data = await response.json().catch(() => ({}));
    throw new Error(
      typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}），请稍后重试`,
    );
  }
  return response.json();
}
export async function restoreSession() {
  try {
    const response = await fetch('/api/auth/me', { credentials: 'same-origin' });
    if (!response.ok) throw new Error('not_authenticated');
    currentUser.value = await response.json();
    connected.value = true;
  } catch {
    currentUser.value = null;
    connected.value = false;
  }
}
export interface NoticeRow {
  id: string;
  code: string;
  execution_time: string;
  department: string;
  creator: string;
  kind: string;
  updated_at: string;
  preview: string;
  reason: string;
  work_number: string;
  project_name: string;
  classification?: string;
  proposed_dept?: string;
  issue_dept: string;
  create_time: string;
  is_effective: string;
  is_discarded: string;
  discard_time: string;
  matches: { field: string; text: string }[];
}
export const fields = [
  ['all', '全部字段'],
  ['fOrderCodeStr', '表单编号'],
  ['fOrderTypeCode', '类别代码'],
  ['fOrderType', '类别描述'],
  ['fClassification', '分类'],
  ['fCreateDeptName', '创建部门'],
  ['fCreatePerson', '创建人员'],
  ['fCheckPerson', '校核人'],
  ['fReviewer', '审查人'],
  ['fAuthorizedPerson', '审定人'],
  ['fApprovalName', '批准人'],
  ['fExecutionTimeStr', '生效时间'],
  ['fWorkPartNumStr', '工作号/部套号'],
  ['fOrderCause', '通知原因'],
  ['fOrderContent', '通知内容'],
  ['fProposedDept', '提出部门'],
] as const;
