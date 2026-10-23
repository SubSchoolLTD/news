"""Inspect genuine review outputs and source health; never generates synthetic events."""
from pathlib import Path
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1];load_dotenv(ROOT/'.env')
import json,re
from concurrent.futures import ThreadPoolExecutor
from app.db import DB,Workspace,Job,Usage,items,now
from app.collect import collect_source
report={'at':now(),'generation_model':'qwen/qwen3.6-35b-a3b','review_model':'google/gemma-4-26b-a4b-it','companies':[]}
with DB() as db:
 for w in db.query(Workspace).all():
  if not w.settings.get('review_variant'):continue
  assert not w.demo
  events=[e for e in items(db,w.id,'event') if e.payload.get('profile_version')==w.profile.get('version')]
  assert events
  for e in events:
   p=e.payload;assert p.get('status')=='verified' and not p.get('is_demo') and p.get('published_at','')<=now()
   assert p.get('profile_features') and p.get('article',{}).get('url','').startswith('https://')
   for b in p.get('bank_evidence',[]):assert ' '.join(p['bank_quote'].split()) in ' '.join(b['text'].split())
  sources=[s for s in items(db,w.id,'source') if s.payload.get('enabled',True)]
  def inspect(s):
   try:
    docs=collect_source({**s.payload,'id':s.id});return s,docs,''
   except Exception as exc:return s,[],str(exc)[:180]
  health=[]
  for s,docs,error in ThreadPoolExecutor(max_workers=4).map(inspect,sources):
   dates=[d['published_at'] for d in docs if d.get('published_at')]
   s.payload={**s.payload,'health':'error' if error else 'ok' if docs else 'empty','last_count':len(docs),'last_checked':now(),'error':error or ('' if docs else 'No current publications returned.'),'latest_publication':max(dates) if dates else s.payload.get('latest_publication') if error else None,'enabled':bool(docs) or bool(error)}
   health.append({k:s.payload.get(k) for k in ['name','url','enabled','health','last_count','latest_publication','target_market','search_provider']})
  briefs=[]
  for period in ['day','week','month']:
   b=next(b for b in items(db,w.id,'brief') if b.payload.get('period')==period and b.payload.get('decision_role')=='ceo' and b.payload.get('profile_version')==w.profile.get('version'))
   p=b.payload;assert not p.get('is_demo')
   for eid in p['event_ids']:
    e=next(e for e in events if e.id==eid);assert p['start']<=(e.payload.get('published_at') or e.created_at)<=p['end']
   assert not re.search(r'\b(must|immediate|immediately|mandatory|urgently)\b',p['en']['executive_summary'],re.I)
   briefs.append({'period':period,'event_count':p['event_count'],'en':p['en'],'ru':p['ru']})
  report['companies'].append({'name':w.name,'regions':w.profile.get('regions'),'profile_version':w.profile.get('version'),'ceo_signals':sum(e.payload['decision_role']=='ceo' for e in events),'cfo_signals':sum(e.payload['decision_role']=='cfo' for e in events),'bank_citations':sum(bool(e.payload.get('bank_ids')) for e in events),'sources':health,'events':[e.payload for e in events],'briefs':briefs})
 db.commit()
out=ROOT/'output/quality/revision-review.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
for c in report['companies']:print(c['name'],'CEO',c['ceo_signals'],'CFO',c['cfo_signals'],'bank',c['bank_citations'],'brief windows',[(b['period'],b['event_count']) for b in c['briefs']],'working sources',sum(s['enabled'] for s in c['sources']))
