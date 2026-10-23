from fastapi.testclient import TestClient
from conftest import register, workspace
from app.main import app
from app.db import DB, Member, User, Workspace, record, now
from app.case_context import build_context, company_choices, dataset_report


def test_case_field_semantics_and_incomplete_group():
    company = {'SYNTHETIC_U':'U1','CL_TYPE':'CLIENT','REVENUE_COMPANY':'1000.0','CityName':'Москва','RCName':'Москва','FTS_COUNTRY_NAME':'ТУРЦИЯ, НИДЕРЛАНДЫ','GROUP_ID':'G1'}
    members=[company,{'SYNTHETIC_U':'U2','CL_TYPE':'CLIENT','GROUP_ID':'G1','MAINOKVED_NAME':'Steel manufacturing','REVENUE_COMPANY':'9000'}]
    payments=[{'PAYER':'U1','BENEFICIARY':'U1','PAY_AMT':'820000','PAY_CNT':'3'}, {'PAYER':'U1','BENEFICIARY':'U2','PAY_AMT':'10000','PAY_CNT':'12'}, {'PAYER':'MISSING','BENEFICIARY':'U1','PAY_AMT':'5000','PAY_CNT':'2'}]
    context, clean=build_context(company,members,payments+payments)
    assert context['revenue']=={'amount':None,'currency':'RUB','year':2025,'scope':'legal_entity'}
    assert clean['REVENUE_COMPANY'] is None
    assert context['servicing_location']['city']=='Москва'
    assert context['trade_countries']==['ТУРЦИЯ','НИДЕРЛАНДЫ']
    assert context['group']['complete'] is False and context['group']['members'][0]['industry']=='Steel manufacturing'
    assert context['payments']['self_transfers']=={'amount_rub':820000,'operation_count':3}
    assert len(context['payments']['external_links'])==2
    known, unknown=context['payments']['external_links']
    assert known['same_group'] and known['relationship_type']=='unknown' and known['amount_rub']==10000
    assert unknown['profile_available'] is False and unknown['industry']==''
    assert 'year not supplied' in context['payments']['period']


def test_case_search_excludes_ambiguous_and_inactive_ids_and_searches_beyond_preview():
    rows=[{'SYNTHETIC_U':f'U{i}','CL_TYPE':'CLIENT','MAINOKVED_NAME':'Industry','REVENUE_COMPANY':'0'} for i in range(50)]
    rows += [{'SYNTHETIC_U':'DUP'},{'SYNTHETIC_U':'DUP'}, {'SYNTHETIC_U':'P','CL_TYPE':'Prospect'}, {'SYNTHETIC_U':'C','CL_TYPE':'Close Client'}]
    assert company_choices(rows,'U49')[0]['id']=='U49'
    assert not company_choices(rows,'DUP') and not company_choices(rows,'P') and not company_choices(rows,'C')
    report=dataset_report(rows)
    assert report['duplicate_ids']==['DUP'] and report['missing_revenue_rows']==54


def test_case_import_is_a_reviewed_draft_without_false_identity_or_market(client):
    register(client);wid=workspace(client)
    with DB() as db:
        w=db.get(Workspace,wid);w.onboarded=True;w.profile={'name':'Real website company','website':'https://example.com','industry':'Education','regions':['Australia'],'exposures':['Technology'],'version':1}
        rows=[{'SYNTHETIC_U':'U1','CL_TYPE':'CLIENT','MAINOKVED_NAME':'Manufacturing','REVENUE_COMPANY':'1000','REGION':'Москва','CL_PRODUCT_LOA_MARK':'1'}]
        r=record(db,wid,'client_dataset',{'rows':rows,'filename':'clients.csv','columns':list(rows[0]),'row_count':1});did=r.id;db.commit()
    data=client.post(f'/api/workspaces/{wid}/datasets/{did}/select',json={'company_id':'U1'}).json()
    assert data['profile']['name']=='Real website company'
    draft=data['draft_profile']
    assert draft['name']=='Case client U1' and draft['website']=='' and draft['regions']==[] and draft['revenue']=='Unknown'
    assert draft['case_context']['servicing_location']['region']=='Москва'
    confirmed=client.put(f'/api/workspaces/{wid}/profile',json={'reviewed':True,'regions':['Turkey']})
    assert confirmed.status_code==200,confirmed.text
    assert confirmed.json()['profile']['version']==2 and confirmed.json()['profile']['regions']==['Turkey']
    repeated=client.post(f'/api/workspaces/{wid}/datasets/{did}/select',json={'company_id':'U1'}).json()
    assert repeated['draft_profile']['regions']==['Turkey']


def test_import_rejects_duplicate_and_inactive_and_requires_tenant_access(client):
    register(client);wid=workspace(client)
    with DB() as db:
        rows=[{'SYNTHETIC_U':'DUP'},{'SYNTHETIC_U':'DUP'},{'SYNTHETIC_U':'CLOSED','CL_TYPE':'Close Client'}]+[{'SYNTHETIC_U':f'U{i}','CL_TYPE':'CLIENT'} for i in range(40)]
        r=record(db,wid,'client_dataset',{'rows':rows,'filename':'clients.csv','columns':list(rows[0]),'row_count':len(rows)});did=r.id;db.commit()
    for cid in ['DUP','CLOSED']:
        assert client.post(f'/api/workspaces/{wid}/datasets/{did}/select',json={'company_id':cid}).status_code==422
    assert client.get(f'/api/workspaces/{wid}/datasets/{did}/companies?q=U39').json()[0]['id']=='U39'
    stranger=TestClient(app);register(stranger,'stranger@example.com')
    assert stranger.get(f'/api/workspaces/{wid}/datasets/{did}/companies?q=U39').status_code==404


def test_hide_signal_is_personal_reversible_and_validated(client):
    owner=register(client);wid=workspace(client)
    other=TestClient(app);reviewer=register(other,'reviewer@example.com')
    with DB() as db:
        db.add(Member(user_id=reviewer['id'],workspace_id=wid,role='viewer'))
        e=record(db,wid,'event',{'en':{'title':'Evidence'},'relevance':80,'published_at':now(),'decision_role':'ceo','profile_version':1});eid=e.id;db.commit()
    path=f'/api/workspaces/{wid}/events/{eid}/visibility'
    assert client.post(path,json={'hidden':'false'}).status_code==422
    assert client.post(path,json={'hidden':True}).status_code==200
    assert client.get(f'/api/workspaces/{wid}/events').json()[0]['hidden_for_me'] is True
    assert other.get(f'/api/workspaces/{wid}/events').json()[0]['hidden_for_me'] is False
    assert client.post(path,json={'hidden':False}).status_code==200
    assert client.get(f'/api/workspaces/{wid}/events').json()[0]['hidden_for_me'] is False
    assert client.post(f'/api/workspaces/{wid}/events/missing/visibility',json={'hidden':True}).status_code==404


def test_analysis_notices_survive_export_and_delivery(client):
    from app.mail import enqueue
    register(client);wid=workspace(client)
    data=client.get(f'/api/workspaces/{wid}/export').json()
    assert 'Not an individual investment recommendation' in data['analysis_notice']['en']
    with DB() as db:
        enqueue(db,wid,'reviewer@example.invalid','Brief','<p>Evidence</p>',key='brief:unit',locale='ru')
        from app.db import items
        assert 'Не является индивидуальной инвестиционной рекомендацией' in items(db,wid,'mail')[0].payload['html']


def test_related_industries_affect_candidate_ranking_with_qualified_reasons():
    from app.research import relevance
    profile={'industry':'Education','case_context':{'group':{'members':[{'industry':'Steel manufacturing'}]},'payments':{'external_links':[{'industry':'Steel manufacturing','profile_available':True}]}}}
    _, reasons=relevance('Steel manufacturing production costs',profile)
    assert 'group member industry (transmission unconfirmed)' in reasons
    assert 'payment counterparty industry (relationship unconfirmed)' in reasons


def test_zero_product_flag_overrides_a_false_model_approval():
    from app.case_context import qualify_reviews
    p={'dataset_features':{'CL_PRODUCT_DEP_MARK':'0.0'},'exposures':['Credit products / borrowing costs']}
    draft={'article_id':'N1','en':{'why':'The company holds deposit products (CL_PRODUCT_DEP_MARK: 0.0, but general liquidity is key).'}}
    review={'reviews':[{'article_id':'N1','supported':True,'issues':[]}]}
    checked=qualify_reviews(p,[draft],review,{})['reviews'][0]
    assert checked['supported'] is False and 'zero CSV flag' in checked['issues'][0]
    assert review['reviews'][0]['supported'] is True
    # A separate user confirmation can legitimately establish a product elsewhere.
    p['exposures']=['Deposits / treasury liquidity']
    assert qualify_reviews(p,[draft],review,{})['reviews'][0]['supported'] is True
    p['exposures']=[];draft['en']['why']='The company does not hold deposit products in the supplied dataset.'
    assert qualify_reviews(p,[draft],review,{})['reviews'][0]['supported'] is True


def test_a_rate_hold_cannot_automatically_raise_existing_borrowing_costs():
    from app.case_context import qualify_reviews
    draft={'article_id':'N1','en':{'fact':'The central bank maintained its key rate at 14%.','impact':'If debt is floating-rate, the sustained rate will increase borrowing costs.'}}
    review={'reviews':[{'article_id':'N1','supported':True,'issues':[]}]}
    assert qualify_reviews({},[draft],review,{})['reviews'][0]['supported'] is False
    draft['en']['impact']='If refinancing is planned, continuing high rates may keep financing costs elevated. Confirm actual loan terms first.'
    assert qualify_reviews({},[draft],review,{})['reviews'][0]['supported'] is True


def test_duplicate_drafts_for_one_news_item_are_not_counted_as_two_events():
    from app.case_context import unique_news_drafts
    rows=[{'article_id':'N1','relevance':70},{'article_id':'N1','relevance':90},{'article_id':'N2','relevance':80}]
    assert unique_news_drafts(rows)==[rows[1],rows[2]]
