<script setup lang="ts">
import { useRoute } from 'vue-router';
const route = useRoute();
</script>
<template>
  <section class="coming-soon">
    <span class="eyebrow">工作空间 / {{ route.meta.title }}</span>
    <div class="coming-symbol">◷</div>
    <h1>{{ route.meta.title }}正在开发中</h1>
    <p>这个模块还在建设，我们会在功能就绪后开放使用。</p>
    <RouterLink to="/notices" class="btn primary">前往技术通知单 →</RouterLink>
  </section>
</template>
