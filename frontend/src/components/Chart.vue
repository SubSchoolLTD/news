<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount,watch} from 'vue'
import {Chart,registerables} from 'chart.js'
Chart.register(...registerables)
const props=defineProps<{data:any,type?:any,options?:any}>()
const canvas=ref<HTMLCanvasElement>()
let chart:Chart
function render(){if(!canvas.value)return;chart?.destroy();chart=new Chart(canvas.value,{type:props.type||'bar',data:props.data,options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{backgroundColor:'#29222f',padding:12,cornerRadius:8}},scales:{x:{grid:{display:false},border:{display:false},ticks:{color:'#96909b',font:{size:11}}},y:{beginAtZero:true,grid:{color:'#eeeaf1'},border:{display:false},ticks:{precision:0,color:'#96909b',font:{size:11}}}},...props.options}})}
onMounted(render);watch(()=>[props.data,props.options],render,{deep:true});onBeforeUnmount(()=>chart?.destroy())
</script>
<template><canvas ref="canvas" role="img" :aria-label="data.datasets?.map((d:any)=>d.label).join(', ')"></canvas></template>
