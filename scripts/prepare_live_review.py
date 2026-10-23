"""Prepare genuine, reproducible review workspaces using the approved model and public news.

No fixture generator is imported. Credentials are supplied on stdin, not command arguments.
"""
from pathlib import Path
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1];load_dotenv(ROOT/'.env')
import csv,json,sys,secrets,re
from app.db import Base,DB,User,Member,Workspace,Item,Job,Usage,engine,items,record,now
from app.pipeline import process_job,period_bounds
from app.research import seed_research
from app.security import hasher
from app.collect import collect_source
args=json.load(sys.stdin);Base.metadata.create_all(engine)
with DB() as db:
 seed_research(db)
 user=db.query(User).filter_by(email=args['email']).first()
 if not user:
  user=User(email=args['email'],name='Jury reviewer',password=hasher.hash(args['password']),verified=True,preferences={'account_kind':'jury','locale':'en','email_alerts':False,'email_briefs':False});db.add(user);db.flush()
 user_id=user.id;db.commit()
def run(wid,kind,data={}):
 with DB() as db:
  j=Job(workspace_id=wid,user_id=user_id,kind=kind,input=data);db.add(j);db.commit();jid=j.id
 process_job(jid)
 with DB() as db:
  j=db.get(Job,jid);print(kind,j.status,j.error[:160],flush=True)
  if j.status!='completed':raise RuntimeError(j.error)
  return j.result
for variant,url in ([] if args.get('export_only') else [('subschool','https://subschool.us'),('eduhub','https://eduhub.blog'),('industrial',None)]):
 with DB() as db:
  w=next((w for w in db.query(Workspace).all() if w.settings.get('review_variant')==variant),None)
  if not w:
   w=Workspace(name=variant,settings={'auto_monitor':False,'scheduled_briefs':[],'interval_minutes':360,'lookback_days':30,'min_relevance':20,'alert_threshold':80,'review_variant':variant});db.add(w);db.flush();db.add(Member(workspace_id=w.id,user_id=user_id,role='owner',decision_role='ceo'));db.commit()
  wid=w.id
 print('Review company:',variant,flush=True)
 if not w.onboarded:
  if url:
   run(wid,'website',{'url':url})
   with DB() as db:
    w=db.get(Workspace,wid);p=w.profile
    p={**p,'name':'SubSchool' if variant=='subschool' else 'EduHub','exposures':['Cloud / technology operating costs','Data privacy / regulation','Consumer demand'] if variant=='subschool' else ['Education policy and funding','Reader demand','AI changes in education'],'priorities':['Sustainable cost per learner','Teacher retention'] if variant=='subschool' else ['Relevant reporting for education decision makers','Audience retention'],'reviewed':True,'status':'confirmed','version':1,'reviewed_at':now()}
    if variant=='eduhub':p['regions']=['United States','Australia']  # Confirmed directly by the product owner.
    p['context_origin']='Public company website. Evaluation priorities are stated assumptions; no private financials or customer contracts are inferred.'
    w.profile=p;w.name=p['name'];w.onboarded=True;w.settings={**w.settings,'keywords':p.get('keywords',[])};db.commit()
  else:
   r=next(csv.DictReader((ROOT/'data/demo_clients.csv').open()))
   with DB() as db:
    w=db.get(Workspace,wid);p={'name':'Case client '+r['SYNTHETIC_U'],'synthetic_company_id':r['SYNTHETIC_U'],'website':'','industry':r['MAINOKVED_NAME'],'activities':[r['MAINOKVED_NAME']],'regions':[r['REGION']],'revenue':r['REVENUE_COMPANY'],'group_id':r['GROUP_ID'],'dataset_features':r,'exposures':['Credit products / borrowing costs','Leasing obligations'],'priorities':['Preserve operating liquidity','Assess refinancing risk'],'unknowns':['Official company identity and website','Fixed versus floating debt terms','Debt maturities and actual cash-flow sensitivity'],'reviewed':True,'version':1,'status':'confirmed','reviewed_at':now(),'context_origin':'Actual anonymised case data. Company identity/website is not established. Evaluation priorities are scenario assumptions.'}
    w.profile=p;w.name=p['name'];w.onboarded=True;w.settings={**w.settings,'keywords':['ключевая ставка','кредиты','инфляция','промышленность','лизинг']};db.commit()
 with DB() as db:
  w=db.get(Workspace,wid)
  if w.profile.get('regions'):
   w.profile={**w.profile,'unknowns':[x for x in w.profile.get('unknowns',[]) if not re.search(r'geograph|primary market regions|географ|регион',x,re.I)]};db.commit()
  if w.settings.get('review_quality_revision')!=2:
   w.profile={**w.profile,'version':int(w.profile.get('version',1))+1}
   w.settings={**w.settings,'review_quality_revision':2}
   db.commit()
 if variant=='eduhub':
  from app.discovery import verify_publisher
  manual=verify_publisher({'url':'https://www.theeducatoronline.com/k12','provider':'Public publisher website inspection','title':'Education trade publisher found in manual review','query':'Education news Australia','target_market':'Australia'})
  with DB() as db:
   record(db,wid,'source',{**manual,'enabled':True,'respect_robots':True,'limit':12,'health':'not_checked','added_by':'Manual review: researched and verified Australian education trade publisher'},key=manual['url']);db.commit()
 if variant!='industrial':
  with DB() as db:
   existing=[s for s in items(db,wid,'source') if s.payload.get('enabled',True)]
  if not existing:
   result=run(wid,'sources')
   with DB() as db:
    for old in items(db,wid,'source'):old.payload={**old.payload,'enabled':False}
    for s in result['sources']:
     record(db,wid,'source',{**s,'enabled':True,'respect_robots':True,'limit':12,'health':'not_checked'},key=s['url'])
    db.commit()
 else:
  # A manually chosen, verified primary source for this Russian credit/lease case.
  s={'id':'review-cbr','name':'Bank of Russia · Press releases','url':'https://www.cbr.ru/rss/RssPress','type':'rss','kind':'news','enabled':True,'respect_robots':True,'limit':20}
  with DB() as db:known=next((r for r in items(db,wid,'source') if r.payload.get('url')==s['url']),None)
  if not known:
   docs=collect_source(s);assert docs,'The primary source must actually be collectable.'
   with DB() as db:record(db,wid,'source',{**s,'added_by':'review preparation: manual primary-source selection','verified_at':now(),'sample_count':len(docs),'health':'ok'},key=s['url']);db.commit()
 with DB() as db:
  if variant=='eduhub':
   needs_new_source=not any(a.payload.get('source_name')==manual['name'] for a in items(db,wid,'article'))
  else:needs_new_source=False
 with DB() as db:has_events=any(e.payload.get('profile_version')==db.get(Workspace,wid).profile.get('version') for e in items(db,wid,'event'))
 if not has_events or needs_new_source:
  result=run(wid,'analyze',{'decision_role':'ceo'})
  if not result.get('events') and not has_events:raise RuntimeError('No verified events for '+variant)
 if variant in ['industrial','subschool']:
  with DB() as db:cfo_ready=any(e.payload.get('decision_role')=='cfo' and e.payload.get('profile_version')==db.get(Workspace,wid).profile.get('version') for e in items(db,wid,'event'))
  if not cfo_ready:run(wid,'analyze',{'decision_role':'cfo'})
 for period in ['day','week','month']:
  with DB() as db:
   start,end=period_bounds(period);version=db.get(Workspace,wid).profile.get('version')
   expected={e.id for e in items(db,wid,'event') if e.payload.get('decision_role')=='ceo' and e.payload.get('profile_version')==version and start<=(e.payload.get('published_at') or e.created_at)<=end}
   existing=any(x.payload.get('period')==period and x.payload.get('decision_role')=='ceo' and x.payload.get('profile_version')==version and set(x.payload.get('event_ids',[]))==expected and not re.search(r'\b(must|immediate|immediately|mandatory|urgently)\b',x.payload.get('en',{}).get('executive_summary',''),re.I) for x in items(db,wid,'brief'))
  if not existing:run(wid,'brief',{'period':period,'decision_role':'ceo'})
 with DB() as db:
  w=db.get(Workspace,wid);w.settings={**w.settings,'showcase':True,'showcase_variant':variant};db.commit()
with DB() as db:
 workspaces=[w for w in db.query(Workspace).all() if w.settings.get('review_variant')]
 for w in workspaces:
  if not w.profile.get('regions'):
   for e in items(db,w.id,'event'):
    p=e.payload
    if p.get('profile_version')!=w.profile.get('version'):continue
    p={**p,'confidence':min(p.get('confidence',65),65)}
    for lang,notice in [('en',"Customer geography is unconfirmed. Validate this market's applicability before acting."),('ru','География клиентов не подтверждена. Сначала проверьте применимость события к вашему рынку.')]:
     p[lang]={**p[lang],'uncertainties':list(dict.fromkeys([notice,*p[lang]['uncertainties']]))[:5]}
    e.payload=p
 db.commit()
 ids=[w.id for w in workspaces]
 def fields(row,names):return {k:getattr(row,k) for k in names}
 export_rows=[]
 for w in workspaces:
  latest_briefs={}
  for r in items(db,w.id,'brief'):
   if r.payload.get('profile_version')==w.profile.get('version'):
    latest_briefs.setdefault((r.payload.get('period'),r.payload.get('decision_role')),r.id)
  for r in db.query(Item).filter_by(workspace_id=w.id).all():
   if r.kind in {'mail','invite','message','saved','feedback'}:continue
   if r.kind=='source' and not r.payload.get('enabled',True):continue
   if r.kind=='event' and r.payload.get('profile_version')!=w.profile.get('version'):continue
   if r.kind=='brief' and r.id not in latest_briefs.values():continue
   export_rows.append(r)

 bundle={'email':args['email'],'password':args['password'],'local_user_id':user_id,'bank_keys':{r.id:r.key for r in items(db,'global','bank')},'workspaces':[fields(w,['id','name','profile','settings','onboarded','demo','created_at']) for w in workspaces],'items':[fields(r,['id','workspace_id','kind','key','payload','created_at','updated_at']) for r in export_rows],'usage':[fields(u,['id','workspace_id','job_id','purpose','model','tokens','latency_ms','status','created_at']) for u in db.query(Usage).filter(Usage.workspace_id.in_(ids)).all()],'jobs':[fields(j,['id','workspace_id','kind','status','progress','input','result','steps','error','created_at','started_at','finished_at']) for j in db.query(Job).filter(Job.workspace_id.in_(ids)).all()]}
 out=ROOT/'.local/review-bundle.json';out.write_text(json.dumps(bundle,ensure_ascii=False));out.chmod(0o600)
 print('Prepared',len(ids),'real workspaces. Private bundle saved.',flush=True)
