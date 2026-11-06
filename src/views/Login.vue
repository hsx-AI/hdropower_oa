<script setup lang="ts">
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api, currentUser, connected, type User } from '../api';
const route = useRoute(),
  router = useRouter();
const username = ref(''),
  password = ref(''),
  busy = ref(false),
  error = ref(''),
  visible = ref(false);
async function submit() {
  busy.value = true;
  error.value = '';
  try {
    currentUser.value = await api<User>('/auth/login', undefined, {
      username: username.value,
      password: password.value,
    });
    connected.value = true;
    password.value = '';
    const next = String(route.query.redirect || '/notices');
    await router.replace(
      next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/login')
        ? next
        : '/notices',
    );
  } catch (e) {
    error.value = e instanceof Error ? e.message : '登录失败';
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <main class="login-page">
    <section class="login-intro">
      <span class="eyebrow">水电分厂 · 数字工作空间</span>
      <h1>让信息更容易找到，<br />让协作更进一步。</h1>
      <p>从一张技术通知单开始，连接工作中的每一处细节。</p>
      <div class="login-illustration" aria-hidden="true">
        <span>技术通知单</span>
        <div>搜索 · 查阅 · 跟踪</div>
        <i></i><i></i><i></i><b>信息有迹可循</b>
      </div>
      <small>水电分厂综合管理平台</small>
    </section>
    <section class="login-side">
      <form class="login-card" @submit.prevent="submit">
        <span class="login-logo">水电 OA</span>
        <h2>欢迎登录</h2>
        <p>使用你的平台账号进入工作空间</p>
        <label
          >账号<input
            v-model.trim="username"
            required
            maxlength="64"
            autocomplete="username"
            placeholder="请输入平台账号" /></label
        ><label
          >密码
          <div class="password-field">
            <input
              v-model="password"
              :type="visible ? 'text' : 'password'"
              required
              maxlength="256"
              autocomplete="current-password"
              placeholder="请输入密码"
            /><button
              type="button"
              @click="visible = !visible"
              :aria-label="visible ? '隐藏密码' : '显示密码'"
            >
              {{ visible ? '隐藏' : '显示' }}
            </button>
          </div></label
        >
        <p v-if="error" class="error-message" role="alert">{{ error }}</p>
        <button class="btn primary login-submit" :disabled="busy">
          {{ busy ? '正在登录…' : '登录工作空间 →' }}</button
        ><small>账号由管理员分配 · 登录后可访问平台业务</small>
      </form>
    </section>
  </main>
</template>
