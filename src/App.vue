<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import Icon from './components/Icon.vue';
import { state, ui } from './stores/platform';
const route = useRoute(),
  router = useRouter();
const collapsed = ref(false),
  mobileNav = ref(false),
  notificationOpen = ref(false),
  profileOpen = ref(false),
  globalSearch = ref('');
const nav = [
  { label: '工作台', icon: 'dashboard', path: '/' },
  { label: '技术通知单', icon: 'file', path: '/notices' },
  { label: '考勤管理', icon: 'calendar', path: '/attendance' },
  { label: '设备管理', icon: 'factory', path: '/equipment' },
  { label: '安灯工单', icon: 'bell', path: '/orders' },
  { label: '交接班管理', icon: 'handover', path: '/handover' },
];
const secondary = [
  { label: '设备台账', icon: 'database', path: '/assets' },
  { label: '统计报表', icon: 'chart', path: '/reports' },
  { label: '基础设置', icon: 'settings', path: '/settings' },
];
const pending = computed(() => state.orders.filter((o) => o.status === '待受理').length);
const day = new Date().toLocaleDateString('zh-CN', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  weekday: 'long',
  timeZone: 'Asia/Shanghai',
});
function search() {
  router.push({ path: '/notices', query: { q: globalSearch.value } });
  globalSearch.value = '';
}
watch(
  () => route.fullPath,
  () => {
    mobileNav.value = false;
    notificationOpen.value = false;
    profileOpen.value = false;
  },
);
</script>
<template>
  <div
    class="application"
    :class="{ 'nav-collapsed': collapsed, 'density-compact': state.settings.compact }"
  >
    <template v-if="!route.meta.mobile"
      ><header class="app-header">
        <div class="brand">
          <button
            class="icon-button mobile-menu"
            aria-label="打开导航"
            @click="mobileNav = !mobileNav"
          >
            <Icon name="menu" /></button
          ><RouterLink to="/" class="brand-link"
            ><span class="brand-mark"><Icon name="zap" :size="23" /></span
            ><span>水电分厂<span class="brand-light">综合管理平台</span></span></RouterLink
          ><span class="brand-divider" /><span class="brand-motto">精益制造 · 智慧管理</span>
        </div>
        <div class="header-right">
          <form class="global-search" @submit.prevent="search">
            <Icon name="search" :size="17" /><input
              v-model="globalSearch"
              aria-label="全局搜索通知单"
              placeholder="搜索技术通知单…"
            /><kbd>↵</kbd>
          </form>
          <div class="header-popover-wrap">
            <button
              class="header-bell icon-button"
              aria-label="查看消息通知"
              @click="
                notificationOpen = !notificationOpen;
                profileOpen = false;
              "
            >
              <Icon name="notification" /><span v-if="pending" class="notification-count">{{
                pending
              }}</span>
            </button>
            <div v-if="notificationOpen" class="header-popover">
              <strong
                >消息通知 <span class="muted">{{ pending }} 条待处理</span></strong
              ><button
                v-for="o in state.orders.filter((o) => o.status === '待受理')"
                :key="o.id"
                @click="router.push({ path: '/orders', query: { id: o.id } })"
              >
                <i class="device-dot fault" /><span
                  >{{ o.device }} {{ o.fault }}<small>{{ o.id }}</small></span
                ><Icon name="right" :size="15" />
              </button>
              <p v-if="!pending" class="muted">暂无待处理安灯工单</p>
            </div>
          </div>
          <span class="header-divider" />
          <div class="header-popover-wrap">
            <button
              class="profile-button"
              @click="
                profileOpen = !profileOpen;
                notificationOpen = false;
              "
            >
              <span class="avatar"><Icon name="user" :size="20" /></span
              ><span class="profile-name"
                ><strong>{{ state.settings.owner }}</strong
                ><small>{{ state.settings.company }} · 管理员</small></span
              ><Icon name="down" :size="14" />
            </button>
            <div v-if="profileOpen" class="header-popover profile-popover">
              <strong>当前为前端演示账号</strong>
              <p>业务操作保存在本机浏览器。</p>
              <RouterLink to="/settings" class="btn"
                >管理演示设置 <Icon name="right" :size="15"
              /></RouterLink>
            </div>
          </div>
        </div>
      </header>
      <div v-if="mobileNav" class="nav-overlay" @click="mobileNav = false" />
      <aside class="sidebar" :class="{ opened: mobileNav }">
        <div class="sidebar-workspace">
          <span class="workspace-icon"><Icon name="building" :size="19" /></span>
          <div><strong>水电分厂</strong><small>综合业务管理空间</small></div>
          <span class="workspace-state" />
        </div>
        <div class="nav-group-label">业务工作空间</div>
        <nav>
          <RouterLink
            v-for="item in nav"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{
              active: item.path === '/' ? route.path === '/' : route.path.startsWith(item.path),
            }"
            :title="item.label"
            ><Icon :name="item.icon" :size="19" /><span>{{ item.label }}</span
            ><span v-if="item.path === '/orders' && pending" class="nav-count">{{
              pending
            }}</span></RouterLink
          >
        </nav>
        <div class="nav-divider" />
        <div class="nav-group-label">数据与管理</div>
        <nav>
          <RouterLink
            v-for="item in secondary"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ active: route.path === item.path }"
            :title="item.label"
            ><Icon :name="item.icon" :size="19" /><span>{{ item.label }}</span></RouterLink
          >
        </nav>
        <div class="sidebar-bottom">
          <div class="system-health">
            <span class="device-dot running" /><span>系统运行正常</span
            ><span class="demo-chip">演示版</span>
          </div>
          <button
            class="collapse-button"
            @click="collapsed = !collapsed"
            :aria-label="collapsed ? '展开导航' : '收起导航'"
          >
            <Icon :name="collapsed ? 'menu' : 'collapse'" :size="17" /><span>收起导航</span>
          </button>
        </div>
      </aside>
      <main class="app-main">
        <div class="breadcrumb">
          <span>{{ state.settings.company }}</span
          ><Icon name="right" :size="13" /><span>{{ route.meta.title }}</span
          ><span class="breadcrumb-date">{{ day }}</span>
        </div>
        <RouterView />
        <footer class="app-footer">
          <span>水电分厂综合管理平台 <span class="footer-dot">·</span> 让生产协同更高效</span
          ><span>{{ route.path.startsWith('/notices') ? '通知单 · 数据库查询' : '其他业务 · 演示数据' }}</span>
        </footer>
      </main></template
    ><RouterView v-else /><Transition name="toast"
      ><div v-if="ui.toast" class="toast-message" :class="ui.toastKind" role="status">
        <Icon :name="ui.toastKind === 'error' ? 'alert' : 'success'" :size="20" />{{ ui.toast }}
      </div></Transition
    >
  </div>
</template>
