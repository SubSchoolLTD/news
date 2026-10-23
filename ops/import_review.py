"""Owner-authorised, idempotent import of genuine review data. Credentials enter via stdin."""
import json,sys
from app.db import Base,DB,User,Member,Workspace,Item,Job,Usage,engine,items
from app.security import hasher
from app.research import seed_research
p=json.load(sys.stdin);Base.metadata.create_all(engine)
with DB() as db:
 seed_research(db)
 u=db.query(User).filter_by(email=p['email']).first()
 if u and u.preferences.get('account_kind')!='jury':raise ValueError('Refusing to replace an existing ordinary account.')
 if not u:
  u=User(email=p['email'],name='Jury reviewer',password=hasher.hash(p['password']),verified=True,preferences={'account_kind':'jury','locale':'en','email_alerts':False,'email_briefs':False});db.add(u);db.flush()
 keys={r.key:r.id for r in items(db,'global','bank')};mapping={old:keys[key] for old,key in p['bank_keys'].items() if key in keys};mapping[p['local_user_id']]=u.id
 def remap(v):
  if isinstance(v,dict):return {k:remap(x) for k,x in v.items()}
  if isinstance(v,list):return [remap(x) for x in v]
  if isinstance(v,str):return mapping.get(v,v)
  return v
 for w in p['workspaces']:
  if w['demo']:raise ValueError('Synthetic demonstration workspaces cannot be imported as live showcases.')
  existing=db.get(Workspace,w['id'])
  if not existing:db.add(Workspace(**remap(w)));db.flush()
  elif not db.query(Member).filter_by(workspace_id=w['id'],user_id=u.id,role='owner').first():raise ValueError('Workspace ownership mismatch.')
  if not db.query(Member).filter_by(workspace_id=w['id'],user_id=u.id).first():db.add(Member(workspace_id=w['id'],user_id=u.id,role='owner',decision_role='ceo'))
 for row in p['items']:
  if row['kind']=='event' and row['payload'].get('is_demo'):raise ValueError('Synthetic events are not allowed in the review bundle.')
  if not db.get(Item,row['id']):db.add(Item(**remap(row)))
 for row in p['jobs']:
  if not db.get(Job,row['id']):db.add(Job(**remap(row),user_id=u.id))
 for row in p.get('usage',[]):
  if not db.get(Usage,row['id']):db.add(Usage(**remap(row)))
 db.commit()
 print('Imported genuine review workspaces:',len(p['workspaces']))
