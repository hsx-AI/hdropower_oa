<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';

const props = defineProps<{ active: boolean; label: string }>();
const value = ref(8);
const waited = ref(0);
let timer: ReturnType<typeof setInterval> | undefined;

function tick() {
  waited.value += 1;
  if (value.value < 92) value.value = Math.min(92, value.value + Math.max(2, (92 - value.value) * 0.22));
}

watch(
  () => props.active,
  (on) => {
    clearInterval(timer);
    if (on) {
      value.value = 8;
      waited.value = 0;
      timer = setInterval(tick, 1000);
    } else {
      value.value = 100;
    }
  },
  { immediate: true },
);
onBeforeUnmount(() => clearInterval(timer));
</script>

<template>
  <div class="task-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" :aria-valuenow="Math.round(value)">
    <div class="task-progress-track"><span :style="{ width: value + '%' }" /></div>
    <p>{{ label }}<span v-if="active"> · 已等待 {{ waited }} 秒</span></p>
  </div>
</template>
