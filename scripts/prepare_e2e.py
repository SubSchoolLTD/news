"""Deterministic browser fixtures. This module is never imported by the application."""
import os,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend/tests'))
from dotenv import load_dotenv
load_dotenv('.env')
from app.db import Base,DB,User,Admin,Workspace,Member,Item,Job,engine,record,items,now
from app.security import hasher
from app.discovery import profile_fingerprint
from fixtures import seed_demo
args=json.load(sys.stdin)
with DB() as db:
 if args['action']=='jury':
  u=User(email=args['email'],name='E2E Jury',password=hasher.hash(args['password']),verified=True,preferences={'account_kind':'jury'});db.add(u);db.flush()
  for variant in ['industrial','subschool']:
   w=seed_demo(db,u,variant);w.demo=False;w.settings={**w.settings,'showcase':True,'showcase_variant':variant}
   for e in items(db,w.id,'event'):e.payload={**e.payload,'is_demo':False}
  a=db.query(Admin).filter_by(email='e2e-ops@example.invalid').first()
  if a:a.password=hasher.hash(args['password'])
  else:db.add(Admin(email='e2e-ops@example.invalid',password=hasher.hash(args['password'])))
  db.commit()
 elif args['action']=='source_result':
  w=db.get(Workspace,args['wid']);p=w.settings.get('profile_draft') or w.profile
  sources=[{'name':'Controlled E2E source','url':'https://example.com/e2e-feed','type':'rss','kind':'news','reason':{'en':'Deterministic browser-test fixture','ru':'Источник для теста интерфейса'},'publisher':'example.com','verified_at':now(),'sample_count':3}]
  result={'status':'completed','sources':sources,'coverage_gaps':[]}
  record(db,w.id,'source_discovery',result,key=profile_fingerprint(p))
  for j in db.query(Job).filter_by(workspace_id=w.id,kind='sources',status='queued').all():j.status='completed';j.progress=100;j.result=result
  db.commit()
 elif args['action']=='verification_link':
  import re,html
  u=db.query(User).filter_by(email=args['email']).one()
  mail=next(x for x in items(db,'auth','mail') if x.payload['to']==u.email and '/verify?token=' in x.payload['html'])
  print(html.unescape(re.search(r'href="([^"]+/verify\?token=[^"]+)"',mail.payload['html'])[1]))
