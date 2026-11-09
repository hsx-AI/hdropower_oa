import { createApp } from 'vue';
import { createRouter, createWebHashHistory } from 'vue-router';
import App from './App.vue';
import './style.css';
import './workspace.css';
import { connected, restoreSession, currentUser } from './api';
const routes = [
  {
    path: '/admin',
    component: () => import('./views/AdminHealth.vue'),
    meta: { title: '系统运维', admin: true },
  },
  { path: '/login', component: () => import('./views/Login.vue'), meta: { title: '登录' } },
  {
    path: '/',
    component: () => import('./views/Dashboard.vue'),
    meta: { title: '工作台', demo: true },
  },
  {
    path: '/notices',
    component: () => import('./views/Notices.vue'),
    meta: { title: '技术通知单' },
  },
  {
    path: '/notices/:id',
    component: () => import('./views/NoticeDetail.vue'),
    meta: { title: '通知单详情' },
  },
  {
    path: '/attendance',
    component: () => import('./views/Attendance.vue'),
    meta: { title: '考勤管理', demo: true },
  },
  {
    path: '/equipment',
    component: () => import('./views/Equipment.vue'),
    meta: { title: '设备数字孪生', demo: true },
  },
  {
    path: '/assets',
    component: () => import('./views/Assets.vue'),
    meta: { title: '设备台账', demo: true },
  },
  {
    path: '/orders',
    component: () => import('./views/Orders.vue'),
    meta: { title: '安灯工单', demo: true },
  },
  {
    path: '/repair',
    component: () => import('./views/Repair.vue'),
    meta: { title: '扫码安灯报修', mobile: true, demo: true },
  },
  {
    path: '/handover',
    component: () => import('./views/Handover.vue'),
    meta: { title: '交接班管理', demo: true },
  },
  {
    path: '/reports',
    component: () => import('./views/Reports.vue'),
    meta: { title: '统计报表', demo: true },
  },
  {
    path: '/settings',
    component: () => import('./views/Settings.vue'),
    meta: { title: '基础设置', demo: true },
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
];
export const router = createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
});
let initialized = false;
router.beforeEach(async (to) => {
  if (!initialized) {
    await restoreSession();
    initialized = true;
  }
  if (!connected.value && to.path !== '/login')
    return { path: '/login', query: { redirect: to.fullPath } };
  if (connected.value && to.path === '/login') return '/notices';
  if (to.meta.admin && currentUser.value?.role !== 'admin') return '/notices';
});
router.afterEach((to) => (document.title = `${to.meta.title} · 水电分厂综合管理平台`));
createApp(App).use(router).mount('#app');
