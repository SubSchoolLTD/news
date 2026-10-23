import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Landing from './views/Landing.vue'
import Auth from './views/Auth.vue'
import Onboard from './views/Onboard.vue'
import Dashboard from './views/Dashboard.vue'
import Events from './views/Events.vue'
import Briefs from './views/Briefs.vue'
import Sources from './views/Sources.vue'
import Settings from './views/Settings.vue'
import Assistant from './views/Assistant.vue'
import Operations from './views/Operations.vue'
import './style.css'

export const router=createRouter({history:createWebHistory(),routes:[
 {path:'/',component:Landing}, {path:'/login',component:Auth}, {path:'/register',component:Auth}, {path:'/verify',component:Auth}, {path:'/reset',component:Auth}, {path:'/invite',component:Auth},
 {path:'/onboarding',component:Onboard}, {path:'/overview',component:Dashboard}, {path:'/events',component:Events}, {path:'/briefs',component:Briefs}, {path:'/sources',component:Sources}, {path:'/company',component:Onboard}, {path:'/settings',component:Settings}, {path:'/assistant',component:Assistant}, {path:'/control',component:Operations}, {path:'/:pathMatch(.*)*',redirect:'/'},
]})
createApp(App).use(router).mount('#app')
