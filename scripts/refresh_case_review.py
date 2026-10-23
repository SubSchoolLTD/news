"""Refresh only the owner's published anonymised case review via the public API.

Uses the originally downloaded case CSVs. Credentials are read from the ignored
owner-only handoff, never printed or sent to any destination except this product.
"""
import argparse,csv,hashlib,io,json,time
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--origin',default='https://analytics.subschool.us');p.add_argument('--prepare-only',action='store_true');p.add_argument('--recheck',action='store_true',help='Confirm a new profile edition and regenerate review analyses');args=p.parse_args()
if args.origin not in {'https://analytics.subschool.us','https://analytics.subschool.ru'}:
    raise ValueError('Use an owner-configured production domain.')
companies=[];payments=[];hashes={}
for path in (ROOT/'.local/case-data').glob('*.csv'):
    with path.open(encoding='utf-8-sig') as f:
        reader=csv.DictReader(f,delimiter=';')
        if 'REVENUE_COMPANY' in (reader.fieldnames or []):
            companies=list(reader);hashes['companies']=hashlib.sha256(path.read_bytes()).hexdigest()
        elif 'PAYER' in (reader.fieldnames or []):
            payments=[r for r in reader if 'U_88715' in {r.get('PAYER'),r.get('BENEFICIARY')}];hashes['payments']=hashlib.sha256(path.read_bytes()).hexdigest()
selected=[r for r in companies if r.get('SYNTHETIC_U')=='U_88715'];assert len(selected)==1,'The review client ID must be unambiguous.'
peer_ids={r.get('PAYER') for r in payments}|{r.get('BENEFICIARY') for r in payments}
subset=[r for r in companies if r.get('SYNTHETIC_U') in peer_ids|{'U_88715'} or r.get('GROUP_ID')==selected[0]['GROUP_ID']]
assert 0<len(subset)<=2000 and len(payments)<=2000,'Do not silently truncate case context.'
def encode(rows):
    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows);return stream.getvalue().encode()
print('Prepared original-case subset:',len(subset),'companies;',len(payments),'payment rows',flush=True)
if args.prepare_only:raise SystemExit(0)
credentials=json.loads((ROOT/'.local/JURY.json').read_text())
with httpx.Client(base_url=args.origin,timeout=45) as client:
    def call(method,path,**kw):
        r=client.request(method,'/api'+path,**kw);r.raise_for_status();return r.json()
    assert call('GET','/health')['version']=='1.2.0','Deploy the semantic guard before refreshing.'
    user=call('POST','/auth/login',json=credentials)
    assert user['preferences'].get('account_kind')=='jury','Refusing an ordinary account.'
    spaces=call('GET','/workspaces');w=next(w for w in spaces if w['settings'].get('showcase_variant')=='industrial')
    assert w['role']=='owner' and w['settings'].get('showcase') and w['profile'].get('synthetic_company_id')=='U_88715'
    base='/workspaces/'+w['id']
    if w['profile'].get('case_context',{}).get('schema_version')!=1:
        # Both datasets are preserved as original evidence, then a reviewed profile is confirmed.
        cid=call('POST',base+'/upload',files={'file':('webinar-case-companies.csv',encode(subset),'text/csv')})['id']
        if payments:call('POST',base+'/upload',files={'file':('webinar-case-payments.csv',encode(payments),'text/csv')})
        call('POST',base+'/datasets/'+cid+'/select',json={'company_id':'U_88715'})
        w=call('PUT',base+'/profile',json={'reviewed':True,'regions':[],'unknowns':['Official company identity and website','Operating and customer markets','Fixed versus floating debt terms','Debt maturities and actual cash-flow sensitivity']})
    elif args.recheck:
        w=call('PUT',base+'/profile',json={'reviewed':True})
    results=[]
    def run(kind,data):
        job=call('POST',base+('/analyze' if kind=='analyze' else '/briefs'),**({'json':data} if kind=='brief' else {}))
        deadline=time.monotonic()+900
        while time.monotonic()<deadline:
            j=call('GET',base+'/jobs/'+job['id'])
            if j['status']=='failed':raise RuntimeError(j['error'])
            if j['status']=='completed':
                print(kind,data,j['result'],flush=True);results.append({'kind':kind,'input':data,'job_id':j['id'],'result':j['result']});return
            time.sleep(2)
        raise TimeoutError('The real case run did not complete.')
    version=w['profile']['version']
    for role in ['ceo','cfo']:
        call('PATCH',base+'/decision-role',json={'role':role})
        existing=call('GET',base+'/events')
        if not existing:run('analyze',{'decision_role':role})
        assert call('GET',base+'/events'),'No verified real-case signals; do not fabricate a replacement.'
    call('PATCH',base+'/decision-role',json={'role':'ceo'})
    briefs=call('GET',base+'/briefs')
    for period in ['day','week','month']:
        if not any(b['period']==period and b.get('profile_version')==version for b in briefs):run('brief',{'period':period})
    # Repeated runs use the confirmed context/version and actual published results.
    output={'at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'origin':args.origin,'workspace_id':w['id'],'profile_version':version,'source_sha256':hashes,'company_rows':len(subset),'payment_rows':len(payments),'context':w['profile']['case_context'],'runs':results}
    dest=ROOT/'output/quality/webinar-case-review.json';dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
