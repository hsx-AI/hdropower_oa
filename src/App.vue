<script setup lang="ts">
import { ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api, currentUser, connected } from './api';
import Icon from './components/Icon.vue';
const route = useRoute(),
  router = useRouter(),
  mobile = ref(false),
  error = ref('');
const nav = [
  ['/notices', '技术通知单', 'file'],
  ['/', '工作台', 'dashboard'],
  ['/attendance', '考勤管理', 'calendar'],
  ['/equipment', '设备管理', 'factory'],
  ['/assets', '设备台账', 'database'],
  ['/orders', '安灯工单', 'bell'],
  ['/repair', '扫码报修', 'bell'],
  ['/handover', '交接班管理', 'handover'],
  ['/reports', '统计报表', 'chart'],
  ['/settings', '基础设置', 'settings'],
];
watch(
  () => route.fullPath,
  () => (mobile.value = false),
);
async function logout() {
  try {
    await api('/auth/logout', undefined, {});
    currentUser.value = null;
    connected.value = false;
    await router.replace('/login');
  } catch (e) {
    error.value = e instanceof Error ? e.message : '退出失败';
  }
}
</script>
<template>
  <RouterView v-if="route.path === '/login'" />
  <div v-else-if="currentUser" class="oa-shell">
    <header class="oa-header">
      <button class="icon-button oa-menu" @click="mobile = !mobile" aria-label="展开导航">
        <Icon name="menu" /></button
      ><RouterLink to="/notices" class="oa-brand"
        ><span>水电</span>
        <div>综合管理平台<small>工作信息，一处汇集</small></div></RouterLink
      >
      <div class="oa-account">
        <span class="account-avatar">{{ currentUser.display_name.slice(0, 1) }}</span>
        <div>
          <strong>{{ currentUser.display_name }}</strong
          ><small>{{ currentUser.role === 'admin' ? '管理员' : '平台用户' }}</small>
        </div>
        <button class="btn small" @click="logout">退出登录</button>
      </div>
    </header>
    <div v-if="mobile" class="oa-overlay" @click="mobile = false"></div>
    <aside class="oa-sidebar" :class="{ open: mobile }">
      <p class="nav-caption">工作空间</p>
      <nav>
        <RouterLink
          v-for="item in nav"
          :key="item[0]"
          :to="item[0]!"
          :class="{
            selected:
              item[0] === '/notices' ? route.path.startsWith('/notices') : route.path === item[0],
          }"
          ><Icon :name="item[2]!" :size="19" /><span>{{ item[1] }}</span
          ><small v-if="item[0] !== '/notices'">开发中</small></RouterLink
        >
      </nav>
      <div class="sidebar-caption">专注每一条工作信息<br /><span>水电分厂综合业务平台</span></div>
    </aside>
    <main class="oa-main">
      <p v-if="error" class="error-message" role="alert">{{ error }}</p>
      <RouterView />
      <footer class="oa-footer">水电分厂综合管理平台 · 让查阅更简单</footer>
    </main>
  </div>
</template>
