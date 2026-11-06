<script setup lang="ts">
import { computed } from 'vue';
const props = defineProps<{ text?: string; query?: string }>();
const parts = computed(() => {
  const text = props.text || '';
  const tokens = (props.query || '').toLowerCase().split(/\s+/).filter(Boolean);
  if (!tokens.length) return [{ text, hit: false }];
  const flags = Array(text.length).fill(false);
  for (const token of tokens) {
    let at = 0;
    while ((at = text.toLowerCase().indexOf(token, at)) !== -1) {
      flags.fill(true, at, at + token.length);
      at += token.length;
    }
  }
  const result: { text: string; hit: boolean }[] = [];
  for (let i = 0; i < text.length; i++) {
    const last = result[result.length - 1];
    if (last && last.hit === flags[i]) last.text += text[i];
    else result.push({ text: text[i]!, hit: flags[i] });
  }
  return result;
});
</script>
<template>
  <template v-for="(part, i) in parts" :key="i"
    ><mark v-if="part.hit">{{ part.text }}</mark
    ><template v-else>{{ part.text }}</template></template
  >
</template>
