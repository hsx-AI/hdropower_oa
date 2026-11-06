<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue';
import { useRoute } from 'vue-router';
import { api, fields, type NoticeRow } from '../api';
import HighlightText from '../components/HighlightText.vue';
const route = useRoute();
const notice = ref<
  | (NoticeRow & {
      content: string;
      fields: Record<string, unknown>;
      tracking: { id: number; status: string; note: string; author: string; created_at: string }[];
    })
  | null
>(null);
const error = ref(''),
  saveError = ref(''),
  busy = ref(false),
  note = ref(''),
  status = ref('处理中'),
  saving = ref(false),
  saved = ref(false);
const query = computed(() => String(route.query.q || ''));
const back = computed(() => {
  const path = String(route.query.from || '');
  return path.startsWith('/notices?') || path === '/notices' ? path : '/notices';
});
let controller: AbortController | undefined;
async function load() {
  controller?.abort();
  const current = new AbortController();
  controller = current;
  busy.value = true;
  error.value = '';
  notice.value = null;
  try {
    const data = await api<NonNullable<typeof notice.value>>(
      '/notices/' + encodeURIComponent(String(route.params.id)),
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
      .replace(/&gt;/g, '>') || '未填写'
  );
}
function value(key: string) {
  return clean(notice.value?.fields[key]);
}
function label(key: string) {
  return fields.find((f) => f[0] === key)?.[1] || key;
}
watch(() => route.params.id, load, { immediate: true });
onBeforeUnmount(() => controller?.abort());
</script>
<template>
  <div class="detail-nav">
    <RouterLink :to="back">← 返回搜索结果</RouterLink><span>技术通知单 / 详细信息</span>
  </div>
  <div v-if="busy" class="empty-search" role="status">正在读取通知单…</div>
  <div v-else-if="error" class="error-message" role="alert">
    {{ error }}<button class="btn" @click="load">重试</button>
  </div>
  <template v-else-if="notice"
    ><header class="document-heading">
      <span class="notice-kind">{{ notice.kind || '技术通知单' }}</span>
      <h1><HighlightText :text="notice.code || notice.id" :query="query" /></h1>
      <p>
        生效时间 {{ notice.execution_time.replace('T', ' ') }} <span>·</span>
        {{ notice.department || '提出部门未填写' }}
      </p>
    </header>
    <div class="document-layout">
      <div>
        <article class="notice-document">
          <div class="document-section">
            <h2>通知内容</h2>
            <p class="document-body">
              <HighlightText :text="notice.content || '源通知单未填写内容'" :query="query" />
            </p>
          </div>
          <div class="document-section">
            <h2>通知原因</h2>
            <p class="document-body">
              <HighlightText :text="value('fOrderCause')" :query="query" />
            </p>
          </div>
          <div class="document-section">
            <h2>工作号 / 部套号</h2>
            <p class="document-body">
              <HighlightText :text="value('fWorkPartNumStr')" :query="query" />
            </p>
          </div>
        </article>
        <section class="document-panel">
          <h2>
            执行跟踪 <span class="muted">{{ notice.tracking.length }} 条</span>
          </h2>
          <p class="section-note">记录执行进展，方便后续查阅。这里的记录保存在本平台。</p>
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
                rows="4"
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
              ><span
                >{{ log.author }} · {{ new Date(log.created_at).toLocaleString('zh-CN') }}</span
              >
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
      </div>
      <aside class="document-aside">
        <section class="document-panel">
          <h2>基本信息</h2>
          <dl>
            <dt>创建人</dt>
            <dd><HighlightText :text="notice.creator || '未填写'" :query="query" /></dd>
            <dt>创建部门</dt>
            <dd>{{ value('fCreateDeptName') }}</dd>
            <dt>提出部门</dt>
            <dd>{{ notice.department || '未填写' }}</dd>
            <dt>分类</dt>
            <dd>{{ value('fClassification') }}</dd>
            <dt>类别</dt>
            <dd>{{ notice.kind || '未填写' }}</dd>
          </dl>
        </section>
        <section class="document-panel">
          <h2>审批信息</h2>
          <dl>
            <template
              v-for="k in ['fCheckPerson', 'fReviewer', 'fAuthorizedPerson', 'fApprovalName']"
              :key="k"
              ><dt>{{ label(k) }}</dt>
              <dd>{{ value(k) }}</dd></template
            >
          </dl>
        </section>
        <p class="section-note">
          最近内容更新<br />{{ new Date(notice.updated_at).toLocaleString('zh-CN') }}
        </p>
      </aside>
    </div></template
  >
</template>
