<script setup lang="ts">
import { ref, reactive, watch, computed, onBeforeUnmount } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api, type NoticeRow } from '../api';
import HighlightText from '../components/HighlightText.vue';
import TaskProgress from '../components/TaskProgress.vue';
const route = useRoute(),
  router = useRouter();
const filter = reactive({
  q: '',
  code: '',
  creator: '',
  kind: '',
  classification: '',
  dept: '',
  work: '',
  discarded: '',
  start: '',
  end: '',
});
const rows = ref<NoticeRow[]>([]),
  total = ref(0),
  loading = ref(false),
  error = ref('');
const page = computed(() => Math.max(1, Number(route.query.page) || 1));
const pages = computed(() => Math.max(1, Math.ceil(total.value / 20)));
const applied = computed(() => String(route.query.q || ''));
const progressLabel = computed(() =>
  applied.value || route.query.creator || route.query.work
    ? '正在按条件检索通知单'
    : '正在读取通知单列表',
);
let controller: AbortController | undefined;
function cell(value?: string | null) {
  return value?.trim() ? value : '';
}
function timeText(value?: string | null) {
  return cell(value).replace('T', ' ').replace(/:\d{2}$/, '');
}
function detailQuery(id: string) {
  return {
    path: '/notices/' + encodeURIComponent(id),
    query: { ...route.query, from: route.fullPath },
  };
}
function statusOf(row: NoticeRow) {
  if (row.is_discarded === '是') return { text: '已废弃', tone: 'bad' };
  if (row.is_discarded === '否') return { text: '在用', tone: 'ok' };
  return { text: '—', tone: '' };
}
async function load() {
  Object.assign(filter, {
    q: String(route.query.q || ''),
    code: String(route.query.code || ''),
    creator: String(route.query.creator || ''),
    kind: String(route.query.kind || ''),
    classification: String(route.query.classification || ''),
    dept: String(route.query.dept || ''),
    work: String(route.query.work || ''),
    discarded: String(route.query.discarded || ''),
    start: String(route.query.start || ''),
    end: String(route.query.end || ''),
  });
  controller?.abort();
  const current = new AbortController();
  controller = current;
  loading.value = true;
  error.value = '';
  const params = new URLSearchParams({ page: String(page.value), size: '20' });
  Object.entries(filter).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  try {
    const data = await api<{ items: NoticeRow[]; total: number }>(
      '/notices?' + params,
      current.signal,
    );
    if (controller === current) {
      rows.value = data.items;
      total.value = data.total;
    }
  } catch (e) {
    if (!current.signal.aborted) {
      rows.value = [];
      error.value = e instanceof Error ? e.message : '查询失败';
    }
  } finally {
    if (controller === current) loading.value = false;
  }
}
function search() {
  if (filter.start && filter.end && filter.start > filter.end) {
    error.value = '开始日期不能晚于结束日期';
    return;
  }
  const query = Object.fromEntries(Object.entries(filter).filter(([, value]) => value));
  if (JSON.stringify(route.query) === JSON.stringify(query)) void load();
  else void router.push({ path: '/notices', query });
}
function reset() {
  Object.assign(filter, {
    q: '',
    code: '',
    creator: '',
    kind: '',
    classification: '',
    dept: '',
    work: '',
    discarded: '',
    start: '',
    end: '',
  });
  search();
}
function go(p: number) {
  void router.push({ query: { ...route.query, page: String(p) } });
}
watch(() => route.fullPath, load, { immediate: true });
onBeforeUnmount(() => controller?.abort());
</script>
<template>
  <section class="notice-board">
    <header class="notice-board-head">
      <div>
        <h1>技术通知单</h1>
        <p>按编号、原因、工作号、人员和日期直接定位，不必先翻完整张单。</p>
      </div>
      <strong v-if="!loading && !error">{{ total.toLocaleString() }} 条</strong>
    </header>
    <form class="notice-filters" @submit.prevent="search">
      <label>关键词<input v-model="filter.q" maxlength="200" placeholder="原因、正文、人员" /></label>
      <label>单据编号<input v-model="filter.code" maxlength="80" placeholder="如 2026水轮机…" /></label>
      <label>编制人<input v-model="filter.creator" maxlength="64" placeholder="姓名" /></label>
      <label>通知类别<input v-model="filter.kind" maxlength="64" placeholder="类别" /></label>
      <label>分类<input v-model="filter.classification" maxlength="64" placeholder="水轮机 / 发电机" /></label>
      <label>单位<input v-model="filter.dept" maxlength="64" placeholder="发出或提出单位" /></label>
      <label>工作号<input v-model="filter.work" maxlength="64" placeholder="工作号 / 部套号" /></label>
      <label
        >是否废弃<select v-model="filter.discarded">
          <option value="">全部</option>
          <option value="否">在用</option>
          <option value="是">已废弃</option>
        </select></label
      >
      <label>生效从<input type="date" v-model="filter.start" /></label>
      <label>至<input type="date" v-model="filter.end" /></label>
      <div class="notice-filter-actions">
        <button class="btn primary" :disabled="loading">查询</button>
        <button type="button" class="btn" @click="reset">清空</button>
      </div>
    </form>
  </section>
  <TaskProgress v-if="loading" :active="loading" :label="progressLabel" />
  <p v-if="error" role="alert" class="error-message">
    {{ error }} <button class="btn" @click="load">重新查询</button>
  </p>
  <section v-else-if="!loading && !rows.length" class="empty-search">
    <h2>没有找到符合条件的通知单</h2>
    <p>试试只填工作号或编制人，或放宽日期。</p>
    <button class="btn" @click="reset">清空条件</button>
  </section>
  <section v-else-if="rows.length" class="notice-table-wrap" :class="{ 'is-loading': loading }">
    <table class="notice-table">
      <thead>
        <tr>
          <th>#</th>
          <th>单据编号</th>
          <th>通知类别</th>
          <th>通知原因</th>
          <th>发出单位</th>
          <th>编制人</th>
          <th>分类</th>
          <th>生效时间</th>
          <th>工作号 / 部套号</th>
          <th>提出部门</th>
          <th>状态</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(n, index) in rows" :key="n.id" @click="router.push(detailQuery(n.id))">
          <td class="num">{{ (page - 1) * 20 + index + 1 }}</td>
          <td class="code">
            <RouterLink :to="detailQuery(n.id)" @click.stop>
              <HighlightText :text="cell(n.code) || n.id" :query="applied" />
            </RouterLink>
          </td>
          <td><HighlightText :text="cell(n.kind)" :query="applied" /></td>
          <td class="reason" :title="cell(n.reason)">
            <span><HighlightText :text="cell(n.reason) || '—'" :query="applied" /></span>
          </td>
          <td><HighlightText :text="cell(n.issue_dept) || cell(n.department)" :query="applied" /></td>
          <td><HighlightText :text="cell(n.creator)" :query="applied" /></td>
          <td><HighlightText :text="cell(n.classification) || cell(n.project_name)" :query="applied" /></td>
          <td class="time">{{ timeText(n.execution_time) }}</td>
          <td><HighlightText :text="cell(n.work_number)" :query="applied" /></td>
          <td><HighlightText :text="cell(n.proposed_dept) || cell(n.department)" :query="applied" /></td>
          <td>
            <span v-if="statusOf(n).tone" class="state-pill" :class="statusOf(n).tone">{{
              statusOf(n).text
            }}</span>
            <span v-else>—</span>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
  <nav v-if="!error && total" class="result-pagination" aria-label="结果翻页">
    <span>第 {{ page }} / {{ pages }} 页 · 每页 20 条 · 点一行打开详情</span>
    <div>
      <button class="btn" :disabled="page <= 1 || loading" @click="go(page - 1)">上一页</button
      ><button class="btn" :disabled="page >= pages || loading" @click="go(page + 1)">下一页</button>
    </div>
  </nav>
</template>
