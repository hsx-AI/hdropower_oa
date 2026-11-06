<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue';
import { useRoute } from 'vue-router';
import ApiAccess from '../components/ApiAccess.vue';
import { api, connected, fields, type NoticeRow } from '../api';
const route = useRoute();
const notice = ref<(NoticeRow & {content: string; fields: Record<string,unknown>; tracking: {id:number;status:string;note:string;author:string;created_at:string}[]}) | null>(null);
const error = ref(''), busy = ref(false), note = ref(''), status = ref('处理中'), saving = ref(false);
async function saveTracking(){saving.value=true;try{await api('/notices/'+encodeURIComponent(String(route.params.id))+'/tracking',undefined,{status:status.value,note:note.value});note.value='';await load();}catch(e){error.value=e instanceof Error?e.message:'保存失败';}finally{saving.value=false;}}
let controller: AbortController | undefined;
async function load() {
  if(!connected.value) return;
  controller?.abort(); const current = new AbortController(); controller=current;
  busy.value=true; error.value=''; notice.value=null;
  try {const value=await api<NonNullable<typeof notice.value>>('/notices/'+encodeURIComponent(String(route.params.id)),current.signal); if(controller===current) notice.value=value;}
  catch(e){if(!current.signal.aborted) error.value=e instanceof Error?e.message:'读取失败';}
  finally{if(controller===current) busy.value=false;}
}
function label(key:string){return fields.find(f=>f[0]===key)?.[1] || key;}
watch([()=>route.params.id,connected],load,{immediate:true});
onBeforeUnmount(()=>controller?.abort());
</script>
<template><ApiAccess><div class="page-heading"><div><h1>{{notice?.code || '技术通知单详情'}}</h1><p>源系统通知单信息</p></div><RouterLink class="btn" to="/notices">返回列表</RouterLink></div>
<div v-if="busy" class="panel empty-state">正在读取…</div><div v-else-if="error" class="panel empty-state" role="alert">{{error}}<button class="btn" @click="load">重试</button></div>
<template v-else-if="notice"><section class="panel detail"><h2>通知内容</h2><p class="content">{{notice.content || '源记录未填写通知内容'}}</p><small>最近内容更新：{{new Date(notice.updated_at).toLocaleString('zh-CN')}}</small></section>
<section class="panel detail"><h2>执行跟踪</h2><p>跟踪记录保存在平台，不回写X5。最近显示200条。</p><form @submit.prevent="saveTracking"><select v-model="status"><option>待处理</option><option>处理中</option><option>已完成</option></select><textarea v-model="note" required maxlength="2000" rows="3" placeholder="填写执行情况" /><button class="btn primary" :disabled="saving || !note.trim()">保存跟踪记录</button></form><article v-for="log in notice.tracking" :key="log.id"><strong>{{log.status}}</strong> · {{log.author}} · {{new Date(log.created_at).toLocaleString('zh-CN')}}<p class="content">{{log.note}}</p></article></section><section class="panel detail"><h2>全部源字段</h2><dl><template v-for="(value,key) in notice.fields" :key="key"><dt>{{label(String(key))}}</dt><dd>{{value === null || value === '' ? '—' : typeof value === 'object' ? JSON.stringify(value) : value}}</dd></template></dl></section></template></ApiAccess></template>
<style scoped>.detail{padding:24px;margin-bottom:20px}.content{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.9;margin:20px 0}dl{display:grid;grid-template-columns:minmax(140px,220px) 1fr;margin-top:16px}dt,dd{padding:12px;border-bottom:1px solid #edf0f4;overflow-wrap:anywhere;white-space:pre-wrap}dt{color:#72849a}@media(max-width:700px){dl{grid-template-columns:1fr}}</style>
