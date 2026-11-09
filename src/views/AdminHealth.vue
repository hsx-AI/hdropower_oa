<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount } from 'vue';
import { api } from '../api';
import Icon from '../components/Icon.vue';
type Status = 'ok' | 'warning' | 'error' | 'unknown' | 'running';
interface Check {
  status: Status;
  message: string;
}
interface Run {
  id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  months_processed: number;
  failed_months: number;
  error_types: Record<string, number>;
}
interface Snapshot {
  checked_at: string;
  overall: Status;
  cached: boolean;
  refresh_after_seconds: number;
  api: Check;
  source: Check & { port?: number };
  services: (Check & {
    id: string;
    name: string;
    enabled?: boolean;
    restarts?: number;
    state?: string;
  })[];
  database: Check & {
    notice_count?: number;
    month_count?: number;
    latency_ms?: number;
    last_data_sync?: string | null;
    last_success?: string | null;
    sync: Check;
    recent_runs: Run[];
  };
}
const data = ref<Snapshot | null>(null),
  loading = ref(false),
  error = ref(''),
  automatic = ref(true);
const labels: Record<string, string> = {
  ok: '正常',
  warning: '需关注',
  error: '异常',
  unknown: '未确认',
  running: '进行中',
  success: '成功',
  partial_failure: '部分失败',
  interrupted: '已中断',
  failed: '失败',
};
const overall = computed(() => data.value?.overall || 'unknown');
const headline = computed(() =>
  error.value
    ? '当前检查未完成'
    : overall.value === 'ok'
      ? '各项检查正常'
      : overall.value === 'error'
        ? '有异常需要处理'
        : overall.value === 'warning'
          ? '有状态需要关注'
          : '正在确认系统状态',
);
const units = computed(() =>
  data.value
    ? [
        { ...data.value.api, id: 'api-response', name: 'API 响应' },
        ...data.value.services,
        { ...data.value.database, id: 'database', name: '数据库查询' },
        { ...data.value.source, id: 'source', name: '源系统网络' },
      ]
    : [],
);
function time(value?: string | null) {
  return value
    ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
    : '暂无记录';
}
let controller: AbortController | undefined, interval: ReturnType<typeof setInterval> | undefined;
async function refresh() {
  if (loading.value) return;
  const current = new AbortController();
  controller = current;
  const deadline = setTimeout(() => current.abort(), 25000);
  loading.value = true;
  error.value = '';
  try {
    data.value = await api<Snapshot>('/admin/health', current.signal);
  } catch (e) {
    error.value = current.signal.aborted
      ? '检查等待超时，请稍后重试。'
      : e instanceof Error
        ? e.message
        : '无法读取系统状态';
  } finally {
    clearTimeout(deadline);
    loading.value = false;
  }
}
onMounted(() => {
  void refresh();
  interval = setInterval(() => {
    if (automatic.value && !document.hidden) void refresh();
  }, 60000);
});
onBeforeUnmount(() => {
  controller?.abort();
  clearInterval(interval);
});
</script>
<template>
  <div class="health-page">
    <header class="health-heading">
      <div>
        <span class="eyebrow">管理员 / 系统运维</span>
        <h1>系统健康检查</h1>
        <p>查看服务是否运行，以及通知单是否真正同步成功。</p>
      </div>
      <div class="health-actions">
        <label><input type="checkbox" v-model="automatic" /> 每分钟自动刷新</label
        ><button class="btn primary" @click="refresh" :disabled="loading">
          <Icon name="refresh" :size="16" />{{ loading ? '正在检查…' : '刷新检查' }}
        </button>
      </div>
    </header>
    <p v-if="error" class="error-message" role="alert">
      {{ error
      }}<span v-if="data">
        下方保留的是 {{ time(data.checked_at) }} 的历史检查结果，不代表当前状态。</span
      >
    </p>
    <section class="health-overview" :class="error ? 'unknown' : overall" aria-live="polite">
      <span class="health-status-dot"></span>
      <div>
        <h2>{{ headline }}</h2>
        <p v-if="data">
          检查时间：{{ time(data.checked_at) }}（北京时间）<span v-if="data.cached">
            · 复用最近检查，约 {{ data.refresh_after_seconds }} 秒后可重新检测</span
          >
        </p>
        <p v-else>{{ loading ? '正在连接后台并检查各项服务…' : '尚未获取检查结果' }}</p>
      </div>
    </section>
    <template v-if="data"
      ><section class="health-grid">
        <article v-for="unit in units" :key="unit.id" class="health-card">
          <header>
            <h2>{{ unit.name }}</h2>
            <span class="health-badge" :class="unit.status">{{ labels[unit.status] }}</span>
          </header>
          <p>{{ unit.message }}</p>
          <dl v-if="'enabled' in unit">
            <div>
              <dt>开机自启</dt>
              <dd>{{ unit.enabled ? '已启用' : '未启用 / 未确认' }}</dd>
            </div>
            <div>
              <dt>服务自动重启次数</dt>
              <dd>{{ unit.restarts ?? '—' }}</dd>
            </div>
          </dl>
          <p
            v-if="unit.id === 'database' && data.database.latency_ms !== undefined"
            class="health-caption"
          >
            连接与查询耗时 {{ data.database.latency_ms }} ms
          </p>
          <p v-if="unit.id === 'source' && data.source.port" class="health-caption">
            目标端口 {{ data.source.port }} · 只检查连接，不采集业务数据
          </p>
        </article>
      </section>
      <section class="health-sync">
        <header>
          <div>
            <h2>通知单同步</h2>
            <p>{{ data.database.sync.message }}</p>
          </div>
          <span class="health-badge" :class="data.database.sync.status">{{
            labels[data.database.sync.status]
          }}</span>
        </header>
        <div class="health-metrics">
          <div>
            <small>已保存通知单</small
            ><strong>{{ data.database.notice_count?.toLocaleString() ?? '—' }}</strong
            ><span>条</span>
          </div>
          <div>
            <small>已采集月份</small><strong>{{ data.database.month_count ?? '—' }}</strong
            ><span>个月</span>
          </div>
          <div>
            <small>最近数据更新</small><b>{{ time(data.database.last_data_sync) }}</b>
          </div>
          <div>
            <small>最近整轮成功</small><b>{{ time(data.database.last_success) }}</b>
          </div>
        </div>
        <p class="health-caption">
          同步服务启动后自动运行，约每小时一轮；单轮耗时超过一小时时，会在本轮结束后继续下一轮。进程运行、网络端口可连均不代表采集成功，请结合下方结果判断。
        </p>
      </section>
      <section class="health-history">
        <h2>最近 10 次同步</h2>
        <div v-if="data.database.recent_runs.length" class="health-table-wrap">
          <table>
            <thead>
              <tr>
                <th>开始时间（北京时间）</th>
                <th>结束时间</th>
                <th>结果</th>
                <th>已处理月份</th>
                <th>失败月份</th>
                <th>错误类型</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="run in data.database.recent_runs" :key="run.id">
                <td>{{ time(run.started_at) }}</td>
                <td>
                  {{
                    run.finished_at
                      ? time(run.finished_at)
                      : run.status === 'running'
                        ? '进行中'
                        : '未记录'
                  }}
                </td>
                <td>
                  <span
                    class="health-badge"
                    :class="
                      run.status === 'success'
                        ? 'ok'
                        : run.status === 'running'
                          ? 'running'
                          : 'error'
                    "
                    >{{ labels[run.status] || '未确认' }}</span
                  >
                </td>
                <td>{{ run.months_processed }}</td>
                <td>{{ run.failed_months }}</td>
                <td>
                  <span v-for="(count, kind) in run.error_types" :key="kind"
                    >{{ kind }} × {{ count }} </span
                  ><span v-if="!Object.keys(run.error_types).length">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="health-caption">暂无同步记录，或数据库状态尚未确认。</p>
      </section></template
    >
    <section class="health-notes">
      <h2>如何判断和处理</h2>
      <p>
        源系统连接超时：检查服务器到源系统的网络、端口与防火墙。最近同步失败：查看失败月份与错误类型，再在服务器核对采集日志。服务未运行：由管理员在服务器检查对应服务。
      </p>
      <p>
        本页为只读检查，不会重启服务或触发采集。检查结果在后台缓存 30
        秒，自动刷新仅在页面可见时进行。API
        或数据库整体故障时，本页也可能无法读取，应从服务器终端检查。
      </p>
    </section>
  </div>
</template>
<style scoped>
.health-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  margin-bottom: 28px;
}
.health-heading h1 {
  font-size: 28px;
  margin: 12px 0;
}
.health-heading p {
  color: #7c8ba0;
  margin: 0;
}
.health-actions {
  display: flex;
  align-items: center;
  gap: 18px;
}
.health-actions label {
  display: flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
  font-size: 12px;
  color: #728199;
}
.health-actions input {
  accent-color: #2563eb;
}
.health-actions button {
  gap: 8px;
  white-space: nowrap;
}
.health-overview {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 24px 28px;
  border: 1px solid #dce5f0;
  border-radius: 13px;
  background: #f0f4fa;
  margin-bottom: 24px;
}
.health-overview h2 {
  font-size: 19px;
  margin: 0 0 8px;
}
.health-overview p {
  margin: 0;
  color: #738198;
  font-size: 12px;
  line-height: 1.8;
}
.health-overview.ok {
  background: #f0faf6;
  border-color: #cbeadc;
}
.health-overview.error {
  background: #fff5f4;
  border-color: #f1d3d0;
}
.health-overview.warning {
  background: #fffbef;
  border-color: #efdfaf;
}
.health-status-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #9ba8ba;
  flex-shrink: 0;
}
.ok > .health-status-dot {
  background: #20a17a;
}
.error > .health-status-dot {
  background: #df635e;
}
.warning > .health-status-dot {
  background: #d2a03a;
}
.health-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  margin-bottom: 24px;
}
.health-card,
.health-sync,
.health-history,
.health-notes {
  border: 1px solid #e1e7ef;
  border-radius: 12px;
  background: white;
  padding: 24px;
}
.health-card header,
.health-sync > header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.health-card h2,
.health-sync h2,
.health-history h2,
.health-notes h2 {
  font-size: 15px;
  margin: 0;
}
.health-card > p {
  font-size: 13px;
  line-height: 1.9;
  color: #6c7d93;
  margin: 16px 0 0;
  overflow-wrap: anywhere;
}
.health-badge {
  display: inline-flex;
  padding: 4px 9px;
  border-radius: 5px;
  font-size: 11px;
  white-space: nowrap;
  background: #edf0f5;
  color: #79879c;
}
.health-badge.ok {
  background: #e9f7f0;
  color: #218764;
}
.health-badge.error {
  background: #ffeded;
  color: #c45050;
}
.health-badge.warning {
  background: #fff5dc;
  color: #a47b23;
}
.health-badge.running {
  background: #eaf1ff;
  color: #3a70c3;
}
.health-card dl {
  margin: 16px 0 0;
  display: grid;
  gap: 10px;
  font-size: 12px;
}
.health-card dl div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.health-card dt {
  color: #95a0b0;
}
.health-card dd {
  margin: 0;
  color: #526780;
}
.health-caption {
  font-size: 12px !important;
  line-height: 1.9;
  color: #8996a7 !important;
}
.health-sync,
.health-history {
  margin-bottom: 24px;
}
.health-sync > header p {
  font-size: 13px;
  color: #7c8da3;
  margin: 8px 0 0;
}
.health-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr 1.5fr 1.5fr;
  gap: 22px;
  padding: 25px 0 15px;
}
.health-metrics small {
  display: block;
  color: #8a98aa;
  font-size: 12px;
  margin-bottom: 14px;
}
.health-metrics strong {
  font-size: 29px;
  letter-spacing: -1px;
}
.health-metrics span {
  font-size: 12px;
  color: #8393a8;
  margin-left: 7px;
}
.health-metrics b {
  font-size: 13px;
  font-weight: 500;
  color: #49617e;
  line-height: 1.8;
}
.health-table-wrap {
  overflow: auto;
  margin-top: 20px;
}
.health-history table {
  font-size: 12px;
  width: 100%;
}
.health-history th,
.health-history td {
  white-space: nowrap;
  padding: 14px 12px;
}
.health-notes {
  background: #f8fafd;
}
.health-notes p {
  font-size: 12px;
  color: #7d8da3;
  line-height: 1.9;
  margin: 14px 0 0;
}
@media (max-width: 1150px) {
  .health-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .health-metrics {
    grid-template-columns: 1fr 1fr;
  }
  .health-heading {
    align-items: start;
    flex-direction: column;
  }
}
@media (max-width: 600px) {
  .health-grid {
    grid-template-columns: 1fr;
  }
  .health-heading h1 {
    font-size: 24px;
  }
  .health-heading p {
    font-size: 12px;
    line-height: 1.8;
  }
  .health-card,
  .health-sync,
  .health-history,
  .health-notes {
    padding: 20px;
  }
  .health-overview {
    padding: 20px;
    align-items: start;
  }
  .health-overview h2 {
    font-size: 17px;
  }
  .health-status-dot {
    margin-top: 4px;
  }
  .health-metrics {
    gap: 22px 15px;
  }
  .health-actions {
    width: 100%;
    justify-content: space-between;
  }
}
</style>
