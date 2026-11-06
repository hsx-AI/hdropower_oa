import { createApp } from 'vue';
import { createRouter, createWebHashHistory } from 'vue-router';
import App from './App.vue';
import './style.css';
import './workspace.css';
import { connected, restoreSession } from './api';
const routes = [
  { path: '/login', component: () => import('./views/Login.vue'), meta: { title: '登录' } },
  { path: '/', component: () => import('./views/ComingSoon.vue'), meta: { title: '工作台' } },
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
    component: () => import('./views/ComingSoon.vue'),
    meta: { title: '考勤管理' },
  },
  {
    path: '/equipment',
    component: () => import('./views/ComingSoon.vue'),
    meta: { title: '设备数字孪生' },
  },
  {
    path: '/assets',
    component: () => import('./views/ComingSoon.vue'),
    meta: { title: '设备台账' },
  },
  {
    path: '/orders',
    component: () => import('./views/ComingSoon.vue'),
    meta: { title: '安灯工单' },
  },
  {
    path: '/repair',
    component: () => import('./views/ComingSoon.vue'),
    meta: { title: '扫码安灯报修', mobile: true },
  },
  {
    path: '/handover',
    component: () => import('./views/ComingSoon.vue'),
    meta: { title: '交接班管理' },
  },
  {
    path: '/reports',
    component: () => import('./views/ComingSoon.vue'),
    meta: { title: '统计报表' },
  },
  {
    path: '/settings',
    component: () => import('./views/ComingSoon.vue'),
    meta: { title: '基础设置' },
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
});
router.afterEach((to) => (document.title = `${to.meta.title} · 水电分厂综合管理平台`));
createApp(App).use(router).mount('#app');
