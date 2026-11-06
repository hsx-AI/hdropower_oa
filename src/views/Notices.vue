<script setup lang="ts">
import { ref, reactive, watch, computed, onBeforeUnmount } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api, fields, type NoticeRow } from '../api';
import HighlightText from '../components/HighlightText.vue';
const route = useRoute(),
  router = useRouter();
const filter = reactive({ q: '', field: 'all', start: '', end: '' });
const rows = ref<NoticeRow[]>([]),
  total = ref(0),
  loading = ref(false),
  error = ref(''),
  advanced = ref(false);
const page = computed(() => Math.max(1, Number(route.query.page) || 1));
const pages = computed(() => Math.max(1, Math.ceil(total.value / 20)));
const applied = computed(() => String(route.query.q || ''));
let controller: AbortController | undefined;
function label(key: string) {
  return fields.find((f) => f[0] === key)?.[1] || '其他信息';
}
async function load() {
  Object.assign(filter, {
    q: String(route.query.q || ''),
    field: String(route.query.field || 'all'),
    start: String(route.query.start || ''),
    end: String(route.query.end || ''),
  });
  if (filter.start || filter.end || filter.field !== 'all') advanced.value = true;
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
  const query = Object.fromEntries(Object.entries(filter).filter(([, v]) => v));
  if (JSON.stringify(route.query) === JSON.stringify(query)) void load();
  else void router.push({ path: '/notices', query });
}
function reset() {
  Object.assign(filter, { q: '', field: 'all', start: '', end: '' });
  search();
}
function go(p: number) {
  void router.push({ query: { ...route.query, page: String(p) } });
}
watch(() => route.fullPath, load, { immediate: true });
onBeforeUnmount(() => controller?.abort());
</script>
<template>
  <section class="notice-hero">
    <span class="eyebrow">通知单资料库</span>
    <h1>找到你需要的那张通知单</h1>
    <p>记得一段内容、一个工作号，或一个人的名字，都可以从这里开始。</p>
    <form @submit.prevent="search">
      <div class="notice-search">
        <span aria-hidden="true">⌕</span
        ><input
          v-model="filter.q"
          maxlength="200"
          aria-label="搜索通知单"
          placeholder="搜索通知内容、编号、工作号、人员…"
        /><button class="btn primary" :disabled="loading">搜索通知单</button>
      </div>
      <div class="search-help">
        <span>支持部分文字匹配 · 多个关键词用空格分隔，结果同时包含这些关键词</span
        ><button
          type="button"
          class="text-button"
          @click="advanced = !advanced"
          :aria-expanded="advanced"
        >
          {{ advanced ? '收起筛选 ↑' : '更多筛选 ↓' }}
        </button>
      </div>
      <div v-if="advanced" class="advanced-search">
        <label
          >搜索范围<select v-model="filter.field">
            <option v-for="f in fields" :key="f[0]" :value="f[0]">{{ f[1] }}</option>
          </select></label
        ><label>生效日期从<input type="date" v-model="filter.start" /></label
        ><label>至<input type="date" v-model="filter.end" /></label
        ><button type="button" class="btn" @click="reset">清空条件</button>
      </div>
    </form>
  </section>
  <div class="results-heading">
    <h2>
      {{ applied ? '搜索结果' : '全部通知单' }}
      <span v-if="!loading && !error">{{ total.toLocaleString() }} 条</span>
    </h2>
    <span>按生效时间由近到远</span>
  </div>
  <p v-if="error" role="alert" class="error-message">
    {{ error }} <button class="btn" @click="load">重新查询</button>
  </p>
  <div v-else-if="loading" class="search-loading" role="status">
    <div v-for="i in 3" :key="i" class="skeleton-card"><i></i><i></i><i></i></div>
    <p>正在查找通知单…</p>
  </div>
  <section v-else-if="!rows.length" class="empty-search">
    <h2>没有找到符合条件的通知单</h2>
    <p>试试缩短关键词、只输入工作号的一部分，或放宽日期范围。</p>
    <button class="btn" @click="reset">清空筛选，查看全部</button>
  </section>
  <section v-else class="notice-results">
    <article v-for="n in rows" :key="n.id" class="notice-result">
      <header>
        <div>
          <span class="notice-kind">{{ n.kind || '技术通知单' }}</span
          ><RouterLink
            :to="{
              path: '/notices/' + encodeURIComponent(n.id),
              query: { ...route.query, from: route.fullPath },
            }"
            class="notice-code"
            ><HighlightText :text="n.code || n.id" :query="applied"
          /></RouterLink>
        </div>
        <time>{{ n.execution_time.replace('T', ' ') }}</time>
      </header>
      <div class="notice-meta">
        <span
          >提出部门 <b><HighlightText :text="n.department || '未填写'" :query="applied" /></b></span
        ><span
          >创建人 <b><HighlightText :text="n.creator || '未填写'" :query="applied" /></b></span
        ><span
          >工作号 / 部套号
          <b><HighlightText :text="n.work_number || '未填写'" :query="applied" /></b
        ></span>
      </div>
      <p class="notice-preview">
        <HighlightText
          :text="n.preview || '该通知单未填写正文，请查看详细信息。'"
          :query="applied"
        />
      </p>
      <p v-if="n.reason" class="notice-reason">
        <strong>通知原因</strong> <HighlightText :text="n.reason" :query="applied" />
      </p>
      <div v-if="applied && n.matches?.length" class="match-list">
        <details>
          <summary>
            查看关键词命中位置（{{ n.matches.length }}{{ n.matches.length === 6 ? '+' : '' }}）
          </summary>
          <p v-for="(m, i) in n.matches" :key="i">
            <strong>{{ label(m.field) }}</strong> <HighlightText :text="m.text" :query="applied" />
          </p>
        </details>
      </div>
      <footer>
        <span>完整正文、审批信息与执行记录</span
        ><RouterLink
          :to="{
            path: '/notices/' + encodeURIComponent(n.id),
            query: { ...route.query, from: route.fullPath },
          }"
          >打开通知单 →</RouterLink
        >
      </footer>
    </article>
  </section>
  <nav v-if="!error && !loading && total" class="result-pagination" aria-label="结果翻页">
    <span>第 {{ page }} / {{ pages }} 页 · 每页 20 条</span>
    <div>
      <button class="btn" :disabled="page <= 1" @click="go(page - 1)">上一页</button
      ><button class="btn" :disabled="page >= pages" @click="go(page + 1)">下一页</button>
    </div>
  </nav>
</template>
