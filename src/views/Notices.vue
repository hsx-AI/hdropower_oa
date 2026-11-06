<script setup lang="ts">
import { ref, reactive, watch, computed, onBeforeUnmount } from 'vue';
import { useRoute } from 'vue-router';
import ApiAccess from '../components/ApiAccess.vue';
import { api, connected, fields, type NoticeRow } from '../api';
const route = useRoute();
const filter = reactive({ q: String(route.query.q || ''), field: 'all', start: '', end: '' });
const applied = ref({ ...filter }), page = ref(1), size = ref(50), total = ref(0);
const rows = ref<NoticeRow[]>([]), loading = ref(false), error = ref(''), syncInfo = ref('');
let request: AbortController | undefined;
const pages = computed(() => Math.max(1, Math.ceil(total.value / size.value)));
const buttons = computed(() => Array.from({length: Math.min(7, pages.value)}, (_, i) => Math.max(1, Math.min(page.value - 3, pages.value - 6)) + i));
async function load() {
  if (!connected.value) return;
  request?.abort(); const current = new AbortController(); request = current;
  loading.value = true; error.value = ''; rows.value = [];
  const params = new URLSearchParams({page: String(page.value), size: String(size.value)});
  Object.entries(applied.value).forEach(([k,v]) => { if(v) params.set(k,v); });
  try { const result = await api<{items: NoticeRow[]; total: number}>('/notices?' + params, current.signal);
    if(request === current) { rows.value = result.items; total.value = result.total; }
  } catch(e) { if(!current.signal.aborted) error.value = e instanceof Error ? e.message : '读取失败'; }
  finally { if(request === current) loading.value = false; }
}
async function syncStatus() {
  if (!connected.value) return;
  try { const s = await api<{runs: {status: string; started_at: string}[]; months: {month: string}[]}>('/sync/status');
    const run = s.runs[0]; const names: Record<string,string> = {success:'完成',running:'进行中',partial_failure:'部分月份失败',interrupted:'中断'};
    syncInfo.value = `已采集 ${s.months.length} 个月` + (run ? ` · 最近同步${names[run.status] || run.status}（${new Date(run.started_at).toLocaleString('zh-CN')}）` : ' · 尚无自动同步记录');
  } catch { syncInfo.value = '同步状态暂不可用'; }
}
function search() {
  if (filter.start && filter.end && filter.start > filter.end) { error.value = '开始日期不能晚于结束日期'; return; }
  applied.value = {...filter}; if(page.value === 1) void load(); else page.value = 1;
}
function reset() { Object.assign(filter, {q:'',field:'all',start:'',end:''}); search(); }
watch([page,size,connected], () => { void load(); void syncStatus(); }, {immediate:true});
watch(() => route.query.q, q => {filter.q = String(q || ''); search();});
onBeforeUnmount(() => request?.abort());
</script>
<template>
  <ApiAccess><div class="page-heading"><div><h1>技术通知单</h1><p>查阅源通知单，按编号、内容、人员和部门检索。</p></div><span class="heading-note">X5 每小时同步</span></div>
  <div class="panel notice-summary">{{ syncInfo }}<button class="btn small" @click="load(); syncStatus()">刷新</button></div>
  <form class="toolbar" @submit.prevent="search"><div class="filter-grid">
    <div class="filter-field"><label>搜索字段</label><select v-model="filter.field"><option v-for="f in fields" :key="f[0]" :value="f[0]">{{f[1]}}</option></select></div>
    <div class="filter-field grow"><label>关键词</label><input v-model.trim="filter.q" maxlength="200" placeholder="输入文字进行包含匹配" aria-label="通知单关键词" /></div>
    <div class="filter-field"><label>生效开始日期</label><input type="date" v-model="filter.start" /></div>
    <div class="filter-field"><label>生效结束日期</label><input type="date" v-model="filter.end" /></div>
  </div><div class="actions"><button class="btn primary">查询</button><button type="button" class="btn" @click="reset">重置</button></div></form>
  <p v-if="error" class="panel notice-summary" role="alert">{{error}} <button class="btn" @click="load">重试</button></p>
  <section class="panel"><div class="table-panel-top">共 {{total.toLocaleString()}} 条通知单</div>
    <div v-if="loading" class="empty-state" role="status">正在查询…</div>
    <div v-else class="table-wrap"><table><thead><tr><th>表单编号</th><th>类别</th><th>提出部门</th><th>创建人员</th><th>生效时间</th><th>操作</th></tr></thead>
    <tbody><tr v-for="n in rows" :key="n.id"><td><RouterLink class="table-title" :to="'/notices/' + encodeURIComponent(n.id)">{{n.code || n.id}}</RouterLink></td><td>{{n.kind || '—'}}</td><td>{{n.department || '—'}}</td><td>{{n.creator || '—'}}</td><td>{{n.execution_time.replace('T',' ')}}</td><td><RouterLink :to="'/notices/' + encodeURIComponent(n.id)">查看详情</RouterLink></td></tr></tbody></table>
    <div v-if="!rows.length && !error" class="empty-state">没有符合条件的通知单</div></div>
    <div class="pagination"><span>第 {{page}} / {{pages}} 页</span><div class="page-buttons"><select v-model="size" @change="page=1"><option :value="20">20条/页</option><option :value="50">50条/页</option><option :value="100">100条/页</option></select><button :disabled="page<=1 || loading" @click="page--">上一页</button><button v-for="p in buttons" :key="p" :class="{active:page===p}" @click="page=p">{{p}}</button><button :disabled="page>=pages || loading" @click="page++">下一页</button></div></div>
  </section></ApiAccess>
</template>
<style scoped>.notice-summary{padding:16px;display:flex;justify-content:space-between;margin-bottom:18px}.actions{display:flex;gap:12px;margin-top:18px}input,select{padding:9px;min-width:0}td{max-width:350px;overflow-wrap:anywhere}</style>
