import { chromium } from '../frontend/node_modules/playwright/index.mjs'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'

// Read the ignored, owner-only handoff locally; never log credentials.
const output = new URL('../output/deployed/', import.meta.url)
await fs.mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const checks = [], errors = []
let release
const pass = name => { checks.push({ name, status: 'passed' }); console.log('PASS', name) }
try {
  for (const [host, language, russian] of [
    ['analytics.subschool.us', 'en-US', false],
    ['analytics.subschool.us', 'ru-RU', true],
    ['analytics.subschool.ru', 'en-US', true],
  ]) {
    const context = await browser.newContext({ locale: language, viewport: { width: 1440, height: 1000 } })
    const page = await context.newPage()
    page.on('pageerror', e => errors.push(e.message))
    await page.goto('https://' + host)
    await page.getByRole('button', { name: russian ? 'Открыть гостевой просмотр' : 'Explore the live tour', exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: 'RU', exact: true }).count(), 0)
    assert.equal(await page.getByRole('button', { name: 'EN', exact: true }).count(), russian ? 1 : 0)
    const health = await page.request.get('https://' + host + '/api/health')
    assert.equal(health.status(), 200)
    const data = await health.json()
    assert.equal(data.status, 'ok')
    if (release) assert.equal(data.release, release)
    release = data.release
    assert.ok(health.headers()['content-security-policy'].includes("default-src 'self'"))
    assert.equal(health.headers()['cache-control'], 'no-store')
    pass(host + ': ' + language + ' → ' + (russian ? 'RU, switch available' : 'EN, switch hidden'))
    await page.screenshot({ path: new URL(host + '-' + language + '.png', output).pathname, fullPage: true })
    await context.close()
  }

  const jury=JSON.parse(await fs.readFile(new URL('../.local/JURY.json',import.meta.url),'utf8'))
  for(const host of ['analytics.subschool.us','analytics.subschool.ru']){
    const ru=host.endsWith('.ru'),base='https://'+host
    const context=await browser.newContext({locale:'en-US',viewport:{width:1440,height:1000}}),page=await context.newPage()
    page.on('pageerror',e=>errors.push(e.message))
    await page.goto(base+'/login')
    await page.getByLabel(ru?'Рабочая почта':'Work email',{exact:true}).fill(jury.email)
    await page.getByLabel(ru?'Пароль':'Password',{exact:true}).fill(jury.password)
    await page.getByRole('button',{name:ru?'Войти':'Sign in',exact:true}).click()
    await page.getByRole('button',{name:ru?'Запустить мониторинг':'Run monitoring',exact:true}).waitFor()
    const owner=await page.request.get(base+'/api/auth/me').then(r=>r.json())
    const workspaces=await page.request.get(base+'/api/workspaces').then(r=>r.json())
    assert.equal(workspaces.length,3);assert.ok(workspaces.every(w=>w.role==='owner'&&!w.demo))
    const cookie=(await context.cookies()).find(c=>c.name==='sd_session');assert.ok(cookie.secure&&cookie.httpOnly&&cookie.sameSite==='Lax')
    await page.goto(base);await page.getByRole('button',{name:ru?'Открыть гостевой просмотр':'Explore the live tour',exact:true}).click()
    await page.getByRole('heading',{name:ru?'Общая картина.':'The bigger picture.',exact:true}).waitFor()
    assert.equal(await page.getByRole('button',{name:ru?'Запустить мониторинг':'Run monitoring',exact:true}).count(),0)
    const headers={'X-SignalDesk-Tour':'1'}
    const tour=await page.request.get(base+'/api/workspaces',{headers}).then(r=>r.json())
    assert.deepEqual(tour.map(w=>w.id).sort(),workspaces.map(w=>w.id).sort());assert.ok(tour.every(w=>w.role==='viewer'))
    assert.equal((await page.request.post(base+'/api/workspaces/'+tour[0].id+'/analyze',{headers})).status(),403)
    const stillOwner=await page.request.get(base+'/api/auth/me').then(r=>r.json());assert.equal(stillOwner.id,owner.id)
    const guest=(await context.cookies()).find(c=>c.name==='sd_guest');assert.ok(guest.secure&&guest.httpOnly)
    await page.screenshot({path:new URL(host+'-guest.png',output).pathname,fullPage:true})
    pass(host+': jury password login, same three real workspaces, read-only guest and preserved account session')
    await context.close()
  }

  let access = ''
  try { access = await fs.readFile(new URL('../.local/ACCESS.md', import.meta.url), 'utf8') } catch {}
  if (access) {
    const [product, ops] = access.split('Operations (independent account):')
    const credentials = section => ({ email: section.match(/Email: (.+)/)[1].trim(), password: section.match(/Password: (.+)/)[1].trim() })
    const owner = credentials(product), admin = credentials(ops)
    const base = 'https://analytics.subschool.us'
    const context = await browser.newContext({ locale: 'en-US', viewport: { width: 1440, height: 1000 } })
    const page = await context.newPage()
    page.on('pageerror', e => errors.push(e.message))
    await page.goto(base + '/login')
    await page.getByLabel('Work email', { exact: true }).fill(owner.email)
    await page.getByLabel('Password', { exact: true }).fill(owner.password)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.waitForURL(url => !url.pathname.endsWith('/login'))
    const ownerState=await page.request.get(base+'/api/auth/me').then(r=>r.json())
    if(!ownerState.verified){await page.getByRole('heading',{name:'Check your inbox.',exact:true}).waitFor();assert.equal((await page.request.get(base+'/api/workspaces')).status(),403)}
    const cookies = await context.cookies()
    const cookie = cookies.find(c => c.name === 'sd_session')
    assert.ok(cookie?.secure && cookie?.httpOnly && cookie?.sameSite === 'Lax')
    assert.equal((await page.request.get(base + '/api/ops/me')).status(), 401)
    pass('Deployed owner sign-in, secure session and administrator realm isolation')
    await context.close()

    const control = await browser.newContext({ locale: 'en-US', viewport: { width: 1440, height: 1000 } })
    const panel = await control.newPage()
    panel.on('pageerror', e => errors.push(e.message))
    await panel.goto(base + '/control')
    await panel.getByLabel('Administrator email', { exact: true }).fill(admin.email)
    await panel.getByLabel('Password', { exact: true }).fill(admin.password)
    await panel.getByRole('button', { name: 'Sign in to operations', exact: true }).click()
    await panel.getByRole('heading', { name: 'The operational picture.', exact: true }).waitFor()
    assert.equal((await panel.request.get(base + '/api/workspaces')).status(), 401)
    await panel.screenshot({ path: new URL('operations.png', output).pathname, fullPage: true })
    pass('Deployed independent administrator sign-in and product realm isolation')
    await control.close()
  }
  assert.deepEqual(errors, [])
  pass('Public bundles load without browser runtime errors')
} catch (error) {
  checks.push({ name: 'Deployed smoke failure', status: 'failed', error: error.message })
  console.error(error.message)
  process.exitCode = 1
} finally {
  await fs.writeFile(new URL('results.json', output), JSON.stringify({ release, at: new Date().toISOString(), checks, errors }, null, 2))
  await browser.close()
}
