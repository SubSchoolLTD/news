"""Paid live-model evaluation on an anonymised client and the dated case-rate scenario.

Creates an isolated demonstration workspace. No email or autonomous external agent.
Run: PYTHONPATH=backend .venv/bin/python scripts/evaluate_case.py
"""
from pathlib import Path
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env')
import csv,json,secrets
from app.db import Base,DB,Workspace,Member,User,Job,Item,record,engine
from app.pipeline import process_job
from app.research import seed_research
from app.security import hasher

Base.metadata.create_all(engine)
row=next(csv.DictReader((ROOT/'data/demo_clients.csv').open()))
with DB() as db:
    seed_research(db)
    user=User(email=f'case-eval-{secrets.token_hex(6)}@example.invalid',name='Case evaluation',password=hasher.hash(secrets.token_urlsafe(25)),preferences={})
    db.add(user);db.flush()
    profile={'name':'Case client '+row['SYNTHETIC_U'],'website':'https://example.com','industry':row['MAINOKVED_NAME'],'regions':[row['REGION']],'revenue':row['REVENUE_COMPANY'],'group_id':row['GROUP_ID'],'activities':[row['MAINOKVED_NAME']],'exposures':['Credit products / borrowing costs'],'priorities':['Assess refinancing risk','Preserve operating liquidity'],'unknowns':['Fixed versus floating loan terms','Actual maturity schedule and cash-flow sensitivity'],'dataset_features':row,'reviewed':True,'version':1,'context_origin':'Anonymised case data. Evaluation priorities are explicit synthetic assumptions; no website-to-client identity mapping.'}
    if row['CL_PRODUCT_LEA_MARK']=='1.0':profile['exposures'].append('Leasing obligations')
    ws=Workspace(name=profile['name'],profile=profile,onboarded=True,demo=True,settings={'auto_monitor':False,'lookback_days':90,'min_relevance':10,'keywords':['ключевая ставка','стоимость кредитов','процентные ставки','ликвидность']})
    db.add(ws);db.flush();db.add(Member(workspace_id=ws.id,user_id=user.id,role='owner',decision_role='cfo'))
    bank=db.query(Item).filter_by(workspace_id='global',kind='bank',key='1shHG89LtMgHT1_uEebHmQSFZe_zbeq7-').one()
    record(db,ws.id,'article',{'title':'Historical case scenario: policy rate unchanged, rhetoric firmer','text':bank.payload['pages_content'][0]['text'][:7000],'url':bank.payload['url'],'source_name':'Provided case scenario · historical research','published_at':'2026-09-11T13:00:00Z','evidence_level':'user_supplied','is_demo':True},key='case-rate-scenario')
    job=Job(workspace_id=ws.id,user_id=user.id,kind='analyze',status='running',input={'decision_role':'cfo'})
    db.add(job);db.commit();jid=job.id;wid=ws.id
print('Evaluating company',row['SYNTHETIC_U'],'with actual case research.',flush=True)
process_job(jid)
with DB() as db:
    job=db.get(Job,jid);events=db.query(Item).filter_by(workspace_id=wid,kind='event').all()
    report={'workspace_id':wid,'job_id':jid,'status':job.status,'error':job.error,'result':job.result,'steps':job.steps,'events':[e.payload for e in events]}
    out=ROOT/'output/quality';out.mkdir(parents=True,exist_ok=True)
    (out/'case-grounding.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('Run:',job.status,job.error,job.result,flush=True)
    for e in events:
        p=e.payload
        print('Insight:',p['en']['title'],'| bank citations:',len(p.get('bank_ids',[])),flush=True)
        print('Company connection:',p['en']['why'],flush=True)
        print('Bank view:',p['en']['bank_view'],flush=True)
    assert job.status=='completed' and events,'No grounded case insights generated; inspect output/quality/case-grounding.json'
    assert any(e.payload.get('bank_ids') for e in events),'Expected exact bank evidence for the policy-rate scenario'
    for event in events:
        p=event.payload
        assert p['profile_features'] and p['profile_version']==1
        if p.get('bank_ids'):
            assert p['bank_quote']
            normal=lambda s:' '.join(s.lower().split())
            assert any(normal(p['bank_quote']) in normal(b['text']) for b in p['bank_evidence'])
    print('PASS: company features, preserved dates, exact bank quotations and independent verification.',flush=True)
