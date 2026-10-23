<script setup lang="ts">
import * as icons from 'lucide-vue-next'
defineProps<{name:string,size?:number}>()
</script>
<template><component :is="(icons as any)[name] || icons.Circle" :size="size||18" :stroke-width="1.7" aria-hidden="true" /></template>
