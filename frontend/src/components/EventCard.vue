<script setup lang="ts">
import {computed} from 'vue'
import Icon from './Icon.vue'
import {state,t,l,fmt} from '../state'
const props=defineProps<{event:any,compact?:boolean}>()
const copy=computed(()=>props.event[state.locale]||props.event.en)
const label=computed(()=>({risk:t('Risk','Риск'),opportunity:t('Opportunity','Возможность'),mixed:t('Mixed impact','Смешанное влияние'),neutral:t('On the radar','На радаре')}[props.event.sentiment]))
</script>
<template><button class="event-card" :class="{compact}" @click="state.selectedEvent=event" :aria-label="copy.title">
  <div class="event-meta"><span class="badge" :class="event.sentiment"><span class="dot"></span>{{label}}</span><span>{{fmt(event.published_at)}}</span><span v-if="event.bank_ids?.length" class="bank-tag">A · {{t('Bank perspective','Мнение банка')}}</span><Icon name="ArrowUpRight" class="event-arrow" :size="17"/></div>
  <h3>{{copy.title}}</h3><p>{{copy.why}}</p>
  <div class="event-footer"><span class="source-icon"><Icon :name="event.is_demo?'FlaskConical':'Newspaper'" :size="13"/>{{event.article?.source_name||t('Workspace source','Источник пространства')}}</span><span class="relevance"><i :style="{width:event.relevance+'%'}"></i><strong>{{event.relevance}}/100</strong> {{t('relevance','релевантность')}}</span></div>
</button></template>
