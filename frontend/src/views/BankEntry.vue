<script setup lang="ts">
import {ref,onMounted,computed} from 'vue'
import {useRouter} from 'vue-router'
import Icon from '../components/Icon.vue'
import AnalysisNotice from '../components/AnalysisNotice.vue'
import {state,t,api,loadWorkspaces,loadData,notify,isGuest,switchWorkspace,setBankMode} from '../state'
const router=useRouter(),busy=ref(false),cases=ref<any[]>([]),selection=ref(state.workspace?.id||'industrial')
const signedIn=computed(()=>state.user&&!isGuest.value&&state.user.verified)
const companies=computed(()=>signedIn.value?state.workspaces.filter(w=>w.onboarded).map(w=>({id:w.id,name:w.name})):cases.value.map(c=>({id:c.variant,name:c.name})))
const company=computed(()=>{
 if(signedIn.value){const w=state.workspaces.find(w=>w.id===selection.value);return w?{name:w.name,event_count:selection.value===state.workspace?.id?state.events.filter(e=>!e.hidden_for_me).length:null,events:selection.value===state.workspace?.id?state.events.filter(e=>!e.hidden_for_me).slice(0,2):[]}:null}
 return cases.value.find(c=>c.variant===selection.value)||cases.value.find(c=>c.variant==='industrial')||cases.value[0]
})
onMounted(async()=>{setBankMode(true);try{cases.value=await api('/showcase/summary');if(!signedIn.value)selection.value=company.value?.variant||'industrial'}catch{}})
async function change(){if(signedIn.value&&selection.value!==state.workspace?.id){busy.value=true;try{await switchWorkspace(selection.value)}catch(e:any){notify(e.message,true)}finally{busy.value=false}}}
async function open(){
 setBankMode(true)
 if(state.user&&!isGuest.value){router.push(state.user.verified?'/events':'/check-email');return}
 busy.value=true
 try{const r=await api('/demo',{method:'POST',body:{variant:selection.value||'industrial'}});sessionStorage.setItem('sd_tour','1');state.user=r.user;await loadWorkspaces(r.workspace_id);await loadData();router.push('/events')}
 catch(e:any){notify(e.message,true)}finally{busy.value=false}
}
</script>
<template>
<div class="bank-preview-app">
 <header><div class="row gap-sm"><span class="bank-mark">A</span><strong>{{t('Alfa-Business','Альфа-Бизнес')}}</strong><span class="badge neutral">{{t('Interactive prototype','Интерактивный прототип')}}</span></div><RouterLink v-if="!signedIn" to="/login" class="btn secondary small-btn">{{t('Account / jury sign in','Вход в аккаунт / для жюри')}}</RouterLink><span v-else class="small muted">{{state.user.name}}</span></header>
 <div class="bank-preview-layout">
  <aside><span class="eyebrow">{{t('COMPANY','КОМПАНИЯ')}}</span><label>{{t('Select company','Выбрать компанию')}}<select v-model="selection" :aria-label="t('Select company','Выбрать компанию')" @change="change" :disabled="busy"><option v-for="c in companies" :key="c.id" :value="c.id">{{c.name}}</option></select></label><h4>{{company?.name||t('Company intelligence','Аналитика компании')}}</h4><button @click="open" :disabled="busy"><Icon name="Radar" :size="18"/>{{t('Business signals','Бизнес-сигналы')}}<span class="count-pill">{{company?.event_count??'—'}}</span></button><RouterLink to="/register" v-if="!signedIn" class="text-link">{{t('Connect my company','Добавить свою компанию')}}</RouterLink><p>{{t('Company switching and the analytics section remain inside this banking prototype.','Переключение компаний и раздел аналитики остаются внутри прототипа банка.')}}</p></aside>
  <main><span class="eyebrow">{{t('YOUR BUSINESS AT A GLANCE','ВАШ БИЗНЕС В ОБЗОРЕ')}}</span><h1>{{t('Good decisions start here.','Здесь начинаются обоснованные решения.')}}</h1><div class="notice"><Icon name="Info" :size="18"/>{{t('Interactive prototype of an internet-bank section. No bank account, payment service or bank SSO is connected.','Интерактивный прототип раздела интернет-банка. Банковский счёт, платежи и банковский SSO не подключены.')}}</div>
  <section class="bank-entry-card"><div class="row between"><span class="eyebrow">{{t('NEWS & BUSINESS INTELLIGENCE','НОВОСТНАЯ БИЗНЕС-АНАЛИТИКА')}}</span><Icon name="Radar" :size="30"/></div><h2>{{t('What’s changing for your business?','Что меняется для вашего бизнеса?')}}</h2><p>{{t('Open a signal, check the original, understand the company-specific consequence and decide what to verify next.','Откройте сигнал, проверьте первоисточник, разберитесь во влиянии на компанию и выберите следующую проверку.')}}</p><div class="bank-preview-signals"><div v-for="e in company?.events||[]" :key="e.en.title"><span class="badge" :class="e.sentiment">{{e.relevance}}/100 {{t('relevance','релевантность')}}</span><strong>{{e[state.locale]?.title}}</strong><span>{{e[state.locale]?.why}}</span></div></div><p v-if="!company?.events?.length" class="muted">{{t('Connect sources and run monitoring to prepare verified signals.','Подключите источники и запустите мониторинг для подготовки проверенных сигналов.')}}</p><button class="btn primary large-btn" @click="open" :disabled="busy"><Icon :name="busy?'LoaderCircle':'ArrowUpRight'" :class="{spin:busy}" :size="18"/>{{t('Open business intelligence','Открыть бизнес-аналитику')}}</button><p class="small muted mt-sm">{{signedIn?t('Your account permissions apply throughout the section.','В разделе действуют права вашего аккаунта.'):t('Read-only tour · sign in to run research','Гостевой просмотр · войдите для запуска анализа')}}</p></section><AnalysisNotice/>
  </main>
 </div>
</div>
</template>
