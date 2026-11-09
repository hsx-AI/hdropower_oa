<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue';
import { useRoute } from 'vue-router';
import { api, fields, type NoticeRow } from '../api';
import HighlightText from '../components/HighlightText.vue';

type DispatchRow = {
  dept_path: string;
  preferred_receiver: string;
  receiver: string;
  received_at: string;
};

type DetailNotice = NoticeRow & {
  content: string;
  fields: Record<string, unknown>;
  detail_header: {
    code: string;
    supplement_status: string;
    issue_dept: string;
    work_part: string;
    reason: string;
    kind: string;
    classification: string;
    creator: string;
    check_person: string;
    reviewer: string;
    authorized_person: string;
    approval_name: string;
    execution_time: string;
  };
  cost: { material: string; process: string; estimate: string };
  dispatch_rows: DispatchRow[];
  dispatch_pending: boolean;
  detail_sync?: { status: string; reason?: string; error_type?: string; synced_at?: string };
  detail_synced_at?: string | null;
  tracking: { id: number; status: string; note: string; author: string; created_at: string }[];
};

const route = useRoute();
const notice = ref<DetailNotice | null>(null);
const error = ref(''),
  saveError = ref(''),
  busy = ref(false),
  note = ref(''),
  status = ref('处理中'),
  saving = ref(false),
  saved = ref(false),
  tab = ref<'content' | 'parts' | 'tools'>('content');
const query = computed(() => String(route.query.q || ''));
const back = computed(() => {
  const path = String(route.query.from || '');
  return path.startsWith('/notices?') || path === '/notices' ? path : '/notices';
});
const header = computed(() => notice.value?.detail_header);
const cost = computed(() => notice.value?.cost);
const syncNote = computed(() => {
  const sync = notice.value?.detail_sync;
  if (!sync) return '';
  if (sync.status === 'synced') return '已从源系统同步本单详细内容';
  if (sync.status === 'fresh') return '使用近期缓存的详细内容（1 小时内）';
  if (sync.status === 'failed') return `源详情同步失败（${sync.error_type || '错误'}），以下为库内已有数据`;
  if (sync.status === 'busy') return '其他会话正在同步本单，以下为库内已有数据';
  if (sync.status === 'skipped') return '未配置详情请求模板，仅显示列表同步字段';
  if (sync.status === 'disabled') return '已关闭按需详情同步';
  return '';
});
let controller: AbortController | undefined;

async function load(refresh = false) {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  busy.value = true;
  error.value = '';
  notice.value = null;
  try {
    const suffix = refresh ? '?refresh=true' : '';
    const data = await api<DetailNotice>(
      '/notices/' + encodeURIComponent(String(route.params.id)) + suffix,
      current.signal,
    );
    if (controller === current) notice.value = data;
  } catch (e) {
    if (!current.signal.aborted) error.value = e instanceof Error ? e.message : '读取失败';
  } finally {
    if (controller === current) busy.value = false;
  }
}

async function save() {
  saving.value = true;
  saveError.value = '';
  saved.value = false;
  try {
    await api('/notices/' + encodeURIComponent(String(route.params.id)) + '/tracking', undefined, {
      status: status.value,
      note: note.value,
    });
    note.value = '';
    await load();
    saved.value = true;
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : '保存失败';
  } finally {
    saving.value = false;
  }
}

function clean(value: unknown) {
  return (
    String(value ?? '')
      .replace(/<br\s*\/?\s*>/gi, '\n')
      .replace(/<\/p>/gi, '\n')
      .replace(/<[^>]+>/g, ' ')
      .replace(/&nbsp;/g, ' ')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>') || ''
  );
}

function label(key: string) {
  return fields.find((f) => f[0] === key)?.[1] || key;
}

watch(
  () => route.params.id,
  () => {
    void load(false);
  },
  { immediate: true },
);
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <div class="detail-nav">
    <RouterLink :to="back">← 返回列表</RouterLink><span>详细信息</span>
  </div>
  <div v-if="busy" class="empty-search" role="status">正在读取通知单并同步源详情…</div>
  <div v-else-if="error" class="error-message" role="alert">
    {{ error }}<button class="btn" @click="load()">重试</button>
  </div>
  <section v-else-if="notice" class="detail-shell">
    <header class="detail-shell-head">
      <h1>详细信息</h1>
      <div class="detail-shell-actions">
        <button type="button" class="btn" :disabled="busy" @click="load(true)">重新同步</button>
        <RouterLink class="detail-shell-close" :to="back" aria-label="关闭">×</RouterLink>
      </div>
    </header>
    <p v-if="syncNote" class="detail-sync-note" role="status">{{ syncNote }}</p>
    <div class="detail-tabs" role="tablist">
      <button
        type="button"
        role="tab"
        class="detail-tab"
        :class="{ active: tab === 'content' }"
        :aria-selected="tab === 'content'"
        @click="tab = 'content'"
      >
        详细内容
      </button>
      <button type="button" role="tab" class="detail-tab" disabled title="即将接入">
        零件及工艺信息
      </button>
      <button type="button" role="tab" class="detail-tab" disabled title="即将接入">工装工具</button>
      <div class="detail-tab-tools" aria-hidden="true">
        <span>打印预览</span><span>流程图</span><span>流程记录</span><span>转发、增发</span>
      </div>
    </div>

    <div v-show="tab === 'content'" class="detail-pane" role="tabpanel">
      <div class="order-sheet">
        <div class="order-sheet-title">技术通知单</div>
        <table class="order-sheet-table">
          <tbody>
            <tr>
              <th>编号：</th>
              <td>
                <HighlightText :text="header?.code || notice.code || notice.id" :query="query" />
              </td>
              <th>补件状态：</th>
              <td>{{ header?.supplement_status || '' }}</td>
              <th>发出单位：</th>
              <td>
                <HighlightText :text="header?.issue_dept || ''" :query="query" />
              </td>
            </tr>
          </tbody>
        </table>

        <table class="order-dispatch-table">
          <thead>
            <tr>
              <th>分发单位</th>
              <th>首选接收人</th>
              <th>接收人</th>
              <th>接收时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!notice.dispatch_rows.length">
              <td colspan="4" class="order-dispatch-empty">
                {{
                  notice.dispatch_pending
                    ? '源详情接口未返回分发单位/接收人（当前已抓取的请求中无此数据）'
                    : ''
                }}
              </td>
            </tr>
            <tr v-for="(row, index) in notice.dispatch_rows" :key="index">
              <td>
                <HighlightText :text="row.dept_path" :query="query" />
              </td>
              <td>
                <HighlightText :text="row.preferred_receiver" :query="query" />
              </td>
              <td>
                <HighlightText :text="row.receiver" :query="query" />
              </td>
              <td>{{ row.received_at }}</td>
            </tr>
          </tbody>
        </table>

        <table class="order-sheet-table order-sheet-body">
          <tbody>
            <tr>
              <th>工作号/部套号/部件名称/部件图号：</th>
              <td colspan="5">
                <HighlightText :text="header?.work_part || ''" :query="query" />
              </td>
            </tr>
            <tr>
              <th>通知单原因：</th>
              <td colspan="5">
                <HighlightText :text="header?.reason || ''" :query="query" />
              </td>
            </tr>
            <tr>
              <th>材料费：</th>
              <td>{{ cost?.material || '' }}</td>
              <th>加工费：</th>
              <td>{{ cost?.process || '' }}</td>
              <th>预计成本：</th>
              <td>{{ cost?.estimate || '' }}</td>
            </tr>
            <tr>
              <th>通知类别：</th>
              <td colspan="2">
                <HighlightText :text="header?.kind || notice.kind || ''" :query="query" />
              </td>
              <th>分类：</th>
              <td colspan="2">
                <HighlightText :text="header?.classification || ''" :query="query" />
              </td>
            </tr>
            <tr>
              <th>编制人：</th>
              <td>
                <HighlightText :text="header?.creator || notice.creator || ''" :query="query" />
              </td>
              <th>校核：</th>
              <td>{{ header?.check_person || '' }}</td>
              <th>审查：</th>
              <td>{{ header?.reviewer || '' }}</td>
            </tr>
            <tr>
              <th>审定：</th>
              <td>{{ header?.authorized_person || '' }}</td>
              <th>批准：</th>
              <td>{{ header?.approval_name || '' }}</td>
              <th>生效时间：</th>
              <td>{{ (header?.execution_time || notice.execution_time || '').replace('T', ' ') }}</td>
            </tr>
            <tr>
              <th>通知内容：</th>
              <td colspan="5" class="order-content-cell">
                <HighlightText :text="notice.content || ''" :query="query" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <section class="document-panel detail-tracking">
      <h2>
        执行跟踪 <span class="muted">{{ notice.tracking.length }} 条</span>
      </h2>
      <p class="section-note">本平台执行记录，不会被源系统同步覆盖。</p>
      <form class="tracking-form" @submit.prevent="save">
        <label
          >执行状态<select v-model="status">
            <option>待处理</option>
            <option>处理中</option>
            <option>已完成</option>
          </select></label
        ><label
          >跟踪说明<textarea
            v-model="note"
            required
            maxlength="2000"
            rows="3"
            placeholder="填写已完成的工作、需要跟进的事项…"
          />
        </label>
        <p v-if="saveError" role="alert" class="error-message">{{ saveError }}</p>
        <p v-if="saved" role="status">跟踪记录已保存</p>
        <button class="btn primary" :disabled="saving || !note.trim()">
          {{ saving ? '正在保存…' : '保存跟踪记录' }}
        </button>
      </form>
      <p v-if="!notice.tracking.length" class="section-note">暂时没有执行记录。</p>
      <article v-for="log in notice.tracking" :key="log.id" class="tracking-entry">
        <header>
          <strong>{{ log.status }}</strong
          ><span>{{ log.author }} · {{ new Date(log.created_at).toLocaleString('zh-CN') }}</span>
        </header>
        <p>{{ log.note }}</p>
      </article>
    </section>

    <details class="document-panel source-fields">
      <summary>全部原始信息</summary>
      <p class="section-note">保留源通知单中的全部字段，便于核对。</p>
      <dl>
        <template v-for="(v, k) in notice.fields" :key="k"
          ><dt>{{ label(String(k)) }}</dt>
          <dd>
            <HighlightText
              :text="typeof v === 'object' && v !== null ? JSON.stringify(v) : clean(v)"
              :query="query"
            /></dd
        ></template>
      </dl>
    </details>
  </section>
</template>
