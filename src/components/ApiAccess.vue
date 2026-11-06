<script setup lang="ts">
import { ref } from 'vue';
import { api, connected, setCredentials } from '../api';
const user = ref(''), password = ref(''), error = ref(''), busy = ref(false);
async function login() {
  busy.value = true; error.value = '';
  try { setCredentials(user.value, password.value); await api('/health'); connected.value = true; password.value = ''; }
  catch (e) { error.value = e instanceof Error ? e.message : '连接失败'; }
  finally { busy.value = false; }
}
</script>
<template>
  <slot v-if="connected" />
  <form v-else class="panel access" @submit.prevent="login">
    <h2>连接通知单管理</h2><p>使用平台访问账号查看已同步的技术通知单。</p>
    <label>账号<input v-model="user" required autocomplete="username" /></label>
    <label>密码<input v-model="password" required type="password" autocomplete="current-password" /></label>
    <p v-if="error" role="alert">{{ error }}</p><button class="btn primary" :disabled="busy">{{ busy ? '正在连接…' : '进入通知单管理' }}</button>
  </form>
</template>
<style scoped>.access {max-width:440px;margin:40px auto;padding:28px}.access label{display:grid;gap:8px;margin:18px 0}.access p{margin:14px 0}.access input{padding:10px}</style>
