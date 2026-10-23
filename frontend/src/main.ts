import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
const Landing=()=>import('./views/Landing.vue')
const Auth=()=>import('./views/Auth.vue')
const CheckEmail=()=>import('./views/CheckEmail.vue')
const Onboard=()=>import('./views/Onboard.vue')
const Dashboard=()=>import('./views/Dashboard.vue')
const Events=()=>import('./views/Events.vue')
const Briefs=()=>import('./views/Briefs.vue')
const Sources=()=>import('./views/Sources.vue')
const Settings=()=>import('./views/Settings.vue')
const Assistant=()=>import('./views/Assistant.vue')
const Operations=()=>import('./views/Operations.vue')
const BankEntry=()=>import('./views/BankEntry.vue')
import './style.css'

export const router=createRouter({history:createWebHistory(),scrollBehavior:(_to,_from,saved)=>saved||{left:0,top:0},routes:[
 {path:'/',component:Landing}, {path:'/login',component:Auth}, {path:'/register',component:Auth}, {path:'/check-email',component:CheckEmail}, {path:'/verify',component:Auth}, {path:'/reset',component:Auth}, {path:'/invite',component:Auth},
 {path:'/alfa-business',component:BankEntry}, {path:'/onboarding',component:Onboard}, {path:'/overview',component:Dashboard}, {path:'/events',component:Events}, {path:'/briefs',component:Briefs}, {path:'/sources',component:Sources}, {path:'/company',component:Onboard}, {path:'/settings',component:Settings}, {path:'/assistant',component:Assistant}, {path:'/control',component:Operations}, {path:'/:pathMatch(.*)*',redirect:'/'},
]})
createApp(App).use(router).mount('#app')
