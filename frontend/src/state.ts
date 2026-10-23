import { reactive, computed } from 'vue'

export const russianAvailable = navigator.language.toLowerCase().startsWith('ru') || location.hostname === 'analytics.subschool.ru'
export const state = reactive({
  locale: (russianAvailable ? localStorage.getItem('sd_locale') || 'ru' : 'en') as 'en'|'ru',
  user: null as any, workspaces: [] as any[], workspace: null as any, config: {} as any,
  ready: false, events: [] as any[], alerts: [] as any[], sources: [] as any[], briefs: [] as any[], jobs: [] as any[], saved: [] as string[],
  toast: '', toastError: false, selectedEvent: null as any, mobileNav: false,
  theme: localStorage.getItem('sd_theme') || 'light',
})
export const t = (en:string,ru:string) => state.locale === 'ru' ? ru : en
export const l = (v:any):string => typeof v === 'object' && v !== null && !Array.isArray(v) ? v[state.locale] || v.en || v.ru || '' : Array.isArray(v) ? v.join(', ') : v ?? ''
export const fmt = (date:string, options:Intl.DateTimeFormatOptions={month:'short',day:'numeric'}) => date ? new Intl.DateTimeFormat(state.locale === 'ru' ? 'ru-RU' : 'en-US',options).format(new Date(date)) : t('Date not reported','Дата не указана')
export const roles = computed(()=>[{id:'ceo',label:t('Chief executive','Генеральный директор')},{id:'cfo',label:t('Finance director','Финансовый директор')},{id:'owner',label:t('Business owner','Владелец бизнеса')},{id:'treasury',label:t('Treasury','Казначейство')},{id:'accountant',label:t('Chief accountant','Главный бухгалтер')},{id:'strategy',label:t('Strategy & operations','Стратегия и операции')}])
export const writeAccess = computed(()=>['owner','admin','analyst'].includes(state.workspace?.role))
export const adminAccess = computed(()=>['owner','admin'].includes(state.workspace?.role))
export const activeJob = computed(()=>state.jobs.find(j=>j.status==='running')||state.jobs.find(j=>j.status==='queued'))

export function notify(message:string,error=false){state.toast=message;state.toastError=error;setTimeout(()=>{if(state.toast===message)state.toast=''},6500)}
export async function api(path:string,options:any={}){
  const {body,...rest}=options
  const headers:any={...options.headers}
  let content=body
  if(body && !(body instanceof FormData)){headers['Content-Type']='application/json';content=JSON.stringify(body)}
  const res=await fetch('/api'+path,{...rest,body:content,headers,credentials:'same-origin'})
  if(!res.ok){let err:any;try{err=await res.json()}catch{err={detail:'Request failed'}};throw new Error(Array.isArray(err.detail)?err.detail.map((e:any)=>e.msg).join('. '):err.detail||t('Something went wrong. Please retry.','Произошла ошибка. Повторите попытку.'))}
  return res.json()
}
export const wp = (path:string) => '/workspaces/'+state.workspace.id+path
export async function loadWorkspaces(preferred?:string){
  state.workspaces=await api('/workspaces')
  const id=preferred||localStorage.getItem('sd_workspace')
  state.workspace=state.workspaces.find(w=>w.id===id)||state.workspaces[0]||null
  if(state.workspace)localStorage.setItem('sd_workspace',state.workspace.id)
}
export async function loadData(){
  if(!state.workspace?.onboarded)return
  const wid=state.workspace.id
  const results=await Promise.allSettled(['/events','/alerts','/sources','/briefs','/jobs','/saved'].map(p=>api('/workspaces/'+wid+p)))
  if(state.workspace?.id!==wid)return
  const keys=['events','alerts','sources','briefs','jobs','saved']
  results.forEach((r,i)=>{if(r.status==='fulfilled')(state as any)[keys[i]]=r.value;else notify(r.reason.message,true)})
}
export async function refreshWorkspace(){if(state.workspace){state.workspace=await api(wp(''));await loadData()}}
export async function switchWorkspace(id:string){state.workspace=state.workspaces.find(w=>w.id===id);localStorage.setItem('sd_workspace',id);state.events=[];state.briefs=[];state.jobs=[];state.sources=[];state.alerts=[];await loadData()}
export async function runAnalysis(){try{const job=await api(wp('/analyze'),{method:'POST'});state.jobs=[job,...state.jobs.filter(j=>j.id!==job.id)];notify(t('Monitoring started. You can keep working while we analyse.','Мониторинг запущен. Вы можете продолжать работу.'))}catch(e:any){notify(e.message,true)}}
export async function bootstrap(){
  try{state.config=await api('/config');state.user=await api('/auth/me');await loadWorkspaces();await loadData()}catch{}finally{state.ready=true}
}
export function setLocale(){state.locale=state.locale==='ru'?'en':'ru';localStorage.setItem('sd_locale',state.locale);document.documentElement.lang=state.locale;if(state.user)api('/auth/me',{method:'PATCH',body:{preferences:{locale:state.locale}}}).catch(()=>{})}
export function setTheme(){state.theme=state.theme==='light'?'dark':'light';localStorage.setItem('sd_theme',state.theme);document.documentElement.dataset.theme=state.theme}
document.documentElement.lang=state.locale
document.documentElement.dataset.theme=state.theme
