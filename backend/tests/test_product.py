import json
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
import pytest

from conftest import register, workspace, verify_user
from app.main import app
from app.db import DB, Admin, Audit, Item, Job, Member, User, Workspace, items, now, record
from app.security import hasher, safe_url
from app.pipeline import period_bounds, run_analysis, generate_brief
from app.research import relevance, retrieve_bank


def test_account_sessions_and_cookie_security(client):
    assert client.get("/api/auth/me").status_code == 401
    user = register(client)
    cookie = client.cookies.get("sd_session")
    assert cookie and "HttpOnly" in client.post("/api/auth/login", json={"email": user["email"], "password": "correct-test-password-123"}).headers["set-cookie"]
    assert client.get("/api/auth/me").json()["email"] == user["email"]
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_cross_workspace_access_is_denied_everywhere(client):
    register(client);wid = workspace(client)
    other = TestClient(app);register(other, "other@example.com")
    for path in ["", "/events", "/sources", "/members", "/research", "/briefs", "/jobs", "/alerts", "/saved", "/export", "/datasets"]:
        assert other.get(f"/api/workspaces/{wid}{path}").status_code == 404, path
    for path in ["/analyze", "/assistant", "/briefs", "/profile/discover", "/invites"]:
        data = {"period": "day", "url": "https://example.com", "email": "x@example.com"}
        assert other.post(f"/api/workspaces/{wid}{path}", json=data).status_code == 404, path


def test_viewer_can_read_and_feedback_but_not_mutate(client):
    owner=register(client);wid=workspace(client)
    with DB() as db:
        m=db.query(Member).filter_by(workspace_id=wid).first();m.role="viewer"
        e=record(db,wid,"event",{"en":{"title":"Test"},"decision_role":"ceo","relevance":80,"published_at":now()})
        eid=e.id;db.commit()
    assert client.get(f"/api/workspaces/{wid}/events").status_code==200
    assert client.post(f"/api/workspaces/{wid}/events/{eid}/feedback",json={"rating":"useful"}).status_code==200
    assert client.post(f"/api/workspaces/{wid}/analyze").status_code==403
    assert client.put(f"/api/workspaces/{wid}/profile",json={"name":"Changed"}).status_code==403
    assert client.patch(f"/api/workspaces/{wid}/settings",json={"keywords":["x"]}).status_code==403
    assert client.put(f"/api/workspaces/{wid}/model",json={"mode":"case"}).status_code==403


def test_invitation_is_email_bound_one_time_and_role_limited(client):
    owner=register(client);verify_user(owner["id"]);wid=workspace(client)
    r=client.post(f"/api/workspaces/{wid}/invites",json={"email":"analyst@example.com","role":"analyst"})
    assert r.status_code==200,r.text
    token=r.json()["invite_url"].split("token=")[1]
    stranger=TestClient(app);register(stranger,"stranger@example.com")
    assert stranger.post(f"/api/invites/{token}/accept").status_code==403
    invited=TestClient(app);register(invited,"analyst@example.com")
    assert invited.post(f"/api/invites/{token}/accept").status_code==200
    assert invited.post(f"/api/invites/{token}/accept").status_code==404
    assert invited.get(f"/api/workspaces/{wid}").json()["role"]=="analyst"
    assert invited.post(f"/api/workspaces/{wid}/invites",json={"email":"x@example.com","role":"admin"}).status_code==403


def test_admin_realm_is_separate_from_product(client):
    register(client)
    assert client.get("/api/ops/overview").status_code==401
    with DB() as db:
        db.add(Admin(email="ops@example.com",password=hasher.hash("admin-test-password-123")));db.commit()
    ops=TestClient(app)
    assert ops.post("/api/ops/login",json={"email":"ops@example.com","password":"admin-test-password-123"}).status_code==200
    assert ops.get("/api/ops/overview").status_code==200
    assert ops.get("/api/workspaces").status_code==401
    assert "Path=/api/ops" in ops.post("/api/ops/login",json={"email":"ops@example.com","password":"admin-test-password-123"}).headers["set-cookie"]


@pytest.mark.parametrize("url",["http://127.0.0.1","http://10.0.0.1","http://169.254.169.254/latest/meta-data/","http://[::1]","file:///etc/passwd","https://user:password@example.com","https://example.com:8443","http://localhost","http://a.internal"])
def test_ssrf_targets_are_blocked(url):
    with pytest.raises(ValueError):safe_url(url)


def test_csrf_cross_origin_write_blocked(client):
    r=client.post("/api/auth/register",headers={"Origin":"https://untrusted.example"},json={"email":"evil@example.com","password":"some-long-password"})
    assert r.status_code==403


def test_private_model_key_never_returned_or_exported(client):
    register(client);wid=workspace(client)
    secret="unit-test-secret-not-an-api-key"
    r=client.put(f"/api/workspaces/{wid}/model",json={"mode":"custom","model":"small-test-model","base_url":"https://example.com/v1","api_key":secret})
    assert r.status_code==200,r.text
    for path in [f"/api/workspaces/{wid}",f"/api/workspaces/{wid}/export",'/api/workspaces']:
        text=client.get(path).text
        assert secret not in text and "key_encrypted" not in text
    with DB() as db:
        stored=db.get(Workspace,wid).settings["model"]["key_encrypted"]
        assert stored and secret not in stored


def test_profile_requires_confirmed_company_exposures(client):
    register(client);wid=workspace(client)
    r=client.put(f"/api/workspaces/{wid}/profile",json={"name":"Maker","industry":"Steel","reviewed":True})
    assert r.status_code==422
    r=client.put(f"/api/workspaces/{wid}/profile",json={"name":"Maker","website":"https://example.com","industry":"Steel","exposures":["Floating-rate debt"],"reviewed":True})
    assert r.status_code==200 and r.json()["onboarded"]
    assert r.json()["profile"]["version"]==1


def test_brief_period_windows_are_distinct():
    end="2026-10-23T12:00:00Z"
    day,_=period_bounds('day',end);week,_=period_bounds('week',end);month,_=period_bounds('month',end)
    assert day=='2026-10-22T12:00:00Z'
    assert week=='2026-10-16T12:00:00Z'
    assert month=='2026-09-23T12:00:00Z'


def test_relevance_changes_with_company_features():
    text="The price of steel and iron rises as energy input costs increase."
    industrial,_=relevance(text,{"industry":"Steel manufacturing","exposures":["Steel and energy input costs"]})
    education,_=relevance(text,{"industry":"Education technology","exposures":["Teacher wages","Student subscriptions"]})
    assert industrial>education+20


def test_bank_retrieval_has_real_page_provenance(client):
    register(client);wid=workspace(client)
    r=client.get(f"/api/workspaces/{wid}/research?q=interest%20rate%20debt%20ставка%20кредит")
    assert r.status_code==200 and len(r.json())>0
    for chunk in r.json():
        assert chunk['url'].startswith('https://drive.google.com/file/d/')
        assert chunk['page']>=1 and len(chunk['text'])>70 and chunk['published_at']


def test_guest_tour_is_read_only_and_uses_published_workspaces(client):
    from fixtures import seed_demo
    owner=register(client)
    with DB() as db:
        for variant in ['industrial','subschool']:
            w=seed_demo(db,db.get(User,owner['id']),variant);w.demo=False
            w.settings={**w.settings,'showcase':True,'showcase_variant':variant}
        db.commit()
    a=client.post('/api/demo',json={'variant':'industrial'}).json();wid=a['workspace_id']
    client.headers['X-SignalDesk-Tour']='1'
    assert a['user']['is_guest']
    assert len(client.get('/api/workspaces').json())==2
    assert client.get(f'/api/workspaces/{wid}').json()['role']=='viewer'
    for path in ['/analyze','/briefs','/assistant','/source-discovery','/sources','/invites']:
        assert client.post(f'/api/workspaces/{wid}'+path,json={'period':'day','name':'Blocked','url':'https://example.com/feed','email':'test@example.invalid'}).status_code==403
    assert client.post('/api/workspaces',json={'name':'Forbidden'}).status_code==403
    assert client.patch('/api/auth/me',json={'name':'Changed'}).status_code==403
    assert client.get(f'/api/workspaces/{wid}/export').status_code==403
    assert client.get(f'/api/workspaces/{wid}/members').status_code==403
    assert client.get(f'/api/workspaces/{wid}/datasets').status_code==403
    b=TestClient(app);other=b.post('/api/demo',json={'variant':'industrial'}).json()
    assert other['workspace_id']==wid and other['user']['id']!=a['user']['id']
    # Opening the tour must not overwrite the signed-in product account.
    del client.headers['X-SignalDesk-Tour']
    assert client.get('/api/auth/me').json()['id']==owner['id']
    assert client.post(f'/api/workspaces/{wid}/analyze').status_code==200


def test_feature_references_resolve_only_exact_confirmed_company_values():
    from app.pipeline import company_feature_keys
    profile={'industry':'EdTech','exposures':['Data privacy / regulation'],'regions':[]}
    assert company_feature_keys(profile,['industry','Data privacy / regulation'])==['industry','exposures']
    assert company_feature_keys(profile,['floating debt','regions','Not confirmed'])==[]


def test_anonymised_import_can_be_reviewed_without_inventing_a_website(client):
    register(client);wid=workspace(client)
    data={'name':'Case client','industry':'Manufacturing','exposures':['Loans'],'reviewed':True}
    assert client.put(f'/api/workspaces/{wid}/profile',json=data).status_code==422
    with DB() as db:
        ws=db.get(Workspace,wid);ws.profile={'synthetic_company_id':'U_TEST','dataset_features':{'PRODUCTS':'loans'}};db.commit()
    assert client.put(f'/api/workspaces/{wid}/profile',json=data).status_code==200


def test_email_verification_is_required_server_side_and_signs_in_other_browser(client):
    import re
    from urllib.parse import urlsplit,parse_qs
    r=client.post('/api/auth/register',json={'name':'New owner','email':'pending@example.invalid','password':'new-secure-password'})
    assert r.status_code==200 and not r.json()['verified']
    assert client.get('/api/auth/me').status_code==200
    assert client.get('/api/workspaces').status_code==403
    assert client.post('/api/workspaces',json={'name':'Blocked'}).status_code==403
    with DB() as db:
        mail=items(db,'auth','mail')[0].payload
        link=re.search(r'href="([^"]+/verify\?token=[^"]+)"',mail['html'])[1]
        token=parse_qs(urlsplit(link).query)['token'][0]
    other=TestClient(app)
    result=other.post('/api/auth/verify',json={'token':token})
    assert result.status_code==200 and result.json()['user']['verified']
    assert other.get('/api/auth/me').status_code==200
    assert other.post('/api/workspaces',json={'name':'Allowed'}).status_code==200
    assert client.get('/api/workspaces').status_code==200
    assert other.post('/api/auth/verify',json={'token':token}).status_code==400


def test_verification_restores_only_a_matching_email_bound_invitation(client):
    import re,html
    from urllib.parse import urlsplit,parse_qs
    register(client);wid=workspace(client)
    link=client.post(f'/api/workspaces/{wid}/invites',json={'email':'invited@example.invalid','role':'viewer'}).json()['invite_url']
    invitation=parse_qs(urlsplit(link).query)['token'][0]
    person=TestClient(app)
    assert person.post('/api/auth/register',json={'email':'invited@example.invalid','password':'secure-test-password','invite_token':invitation}).status_code==200
    assert person.post('/api/invites/'+invitation+'/accept').status_code==403
    with DB() as db:
        mail=next(x.payload for x in items(db,'auth','mail') if x.payload['to']=='invited@example.invalid')
        token=parse_qs(urlsplit(html.unescape(re.search(r'href="([^"]+/verify\?token=[^"]+)"',mail['html'])[1])).query)['token'][0]
    fresh=TestClient(app)
    assert fresh.post('/api/auth/verify',json={'token':token}).json()['invite_token']==invitation
    assert fresh.post('/api/invites/'+invitation+'/accept').status_code==200
    assert fresh.get(f'/api/workspaces/{wid}').json()['role']=='viewer'


def test_source_discovery_has_no_default_outlets_and_invalidates_on_market_change(client,monkeypatch):
    import app.discovery as discovery
    from app.pipeline import process_job
    owner=register(client);wid=workspace(client)
    profile={'name':'Education publisher','website':'https://example.com','industry':'Education news','regions':['United States','Australia'],'exposures':['Reader demand']}
    assert client.put(f'/api/workspaces/{wid}/profile',json=profile).status_code==200
    assert client.get(f'/api/workspaces/{wid}/source-suggestions').json()==[]
    seen=[]
    def search(q):
        seen.append(q)
        return [{'url':'https://publisher.example/news','title':'Education policy','country':'Australia','provider':'Test index','query':q}, {'url':'http://127.0.0.1/private','title':'Attack','country':'','provider':'Test','query':q}]
    monkeypatch.setattr(discovery,'search_index',search)
    monkeypatch.setattr(discovery,'search_web',lambda q:[])
    monkeypatch.setattr(discovery,'search_directory',lambda q:[])
    monkeypatch.setattr(discovery,'verify_publisher',lambda h:{'name':'Publisher','url':'https://example.com/education-feed','type':'rss','kind':'news','publisher':'publisher.example','country':h['country'],'sample_count':3,'sample_headlines':['Education policy'],'verified_at':now()})
    def complete(w,purpose,prompt,**kw):
        if purpose=='source_search_plan':return {'markets':['United States','Australia'],'queries':[{'news_query':'education sourcecountry:australia','web_query':'education Australia RSS'}]}
        return {'sources':[{'id':'S1','eligible':True,'reason':{'en':'Relevant education policy in Australia','ru':'Образовательная политика Австралии'}},{'id':'invented','reason':{'en':'x','ru':'x'}}]}
    monkeypatch.setattr(discovery.llm,'complete',complete)
    j=client.post(f'/api/workspaces/{wid}/source-discovery').json();process_job(j['id'])
    sources=client.get(f'/api/workspaces/{wid}/source-suggestions').json()
    assert seen==['education sourcecountry:australia'] and len(sources)==1
    assert sources[0]['sample_count']==3 and sources[0]['country']=='Australia'
    connected=client.post(f'/api/workspaces/{wid}/sources',json={'name':sources[0]['name'],'url':sources[0]['url'],'type':'rss','kind':'news'}).json()
    assert connected['verified_at'] and connected['sample_count']==3
    assert client.put(f'/api/workspaces/{wid}/profile',json={**profile,'regions':['Canada']}).status_code==200
    assert client.get(f'/api/workspaces/{wid}/source-suggestions').json()==[]


def test_unsupported_ai_drafts_are_withheld(client,monkeypatch):
    from app import pipeline
    owner=register(client);wid=workspace(client)
    with DB() as db:
        ws=db.get(Workspace,wid);ws.onboarded=True;ws.profile={"industry":"Steel","exposures":["steel prices"],"version":1};ws.settings={"min_relevance":0}
        a=record(db,wid,'article',{"title":"Steel prices change","text":"Steel prices change with manufacturing demand.","published_at":now(),"url":"https://example.com/news","evidence_level":"user_supplied"});aid=a.id
        source=record(db,wid,'source',{'name':'Test source','url':'https://example.com/feed','enabled':True,'type':'rss'});sid=source.id
        j=Job(workspace_id=wid,user_id=owner['id'],kind='analyze',status='running',input={});db.add(j);db.commit()
        def collect(s):
            assert client.patch(f'/api/workspaces/{wid}/sources/{sid}',json={'enabled':False}).status_code==200
            return [],[{'id':sid,'status':'ok','count':0}]
        monkeypatch.setattr(pipeline,'collect_sources',collect)
        def complete(ws,purpose,prompt,**kwargs):
            if purpose=='analysis_plan':return {"research_query":"steel prices","missing_data":[]}
            if purpose=='interpret_events':
                assert client.patch(f'/api/workspaces/{wid}/settings',json={'auto_monitor':False,'keywords':['updated during analysis']}).status_code==200
                return {"events":[{"article_id":aid,"en":{"title":"Unsupported"},"ru":{"title":"Unsupported"}}]}
            return {"reviews":[{"article_id":aid,"supported":False,"issues":["Invented company debt"]}]}
        monkeypatch.setattr(pipeline.llm,'complete',complete)
        run_analysis(db,j,ws);db.commit()
        assert not items(db,wid,'event')
        assert j.result['rejected']==1
        assert any(s['name']=='adapt' for s in j.steps)
        current=client.get(f'/api/workspaces/{wid}').json()['settings']
        assert current['auto_monitor'] is False and current['keywords']==['updated during analysis']
        assert client.get(f'/api/workspaces/{wid}/sources').json()[0]['enabled'] is False


def test_brief_rejects_invented_citation_ids(client,monkeypatch):
    from app import pipeline
    owner=register(client);wid=workspace(client)
    with DB() as db:
        ws=db.get(Workspace,wid)
        record(db,wid,'event',{"decision_role":"ceo","published_at":now(),"relevance":90,"sentiment":"risk","en":{"title":"Test"},"ru":{"title":"Тест"}})
        j=Job(workspace_id=wid,user_id=owner['id'],kind='brief',input={"period":"day"});db.add(j);db.commit()
        lang={"title":"Test brief","executive_summary":"Test","themes":[{"title":"x","event_ids":["invented"]}],"priorities":[{"action":"x","event_ids":["invented"]}]}
        monkeypatch.setattr(pipeline.llm,'complete',lambda *args,**kwargs:{"en":lang.copy(),"ru":lang.copy()})
        with pytest.raises(ValueError,match='evidence references'):generate_brief(db,j,ws)
        assert not items(db,wid,'brief')


def test_brief_withholds_unresolved_company_context_claims(client,monkeypatch):
    from app import pipeline
    owner=register(client);wid=workspace(client)
    with DB() as db:
        ws=db.get(Workspace,wid)
        event=record(db,wid,'event',{'decision_role':'ceo','published_at':now(),'relevance':80,'sentiment':'risk','en':{'title':'Conditional signal'},'ru':{'title':'Условный сигнал'}})
        j=Job(workspace_id=wid,user_id=owner['id'],kind='brief',input={'period':'day'});db.add(j);db.commit()
        section={'title':'Unsupported certainty','executive_summary':'Company must pivot','themes':[{'title':'x','event_ids':[event.id]}],'priorities':[{'action':'x','event_ids':[event.id]}]}
        def complete(w,purpose,*a,**kw):
            return {'supported':False,'issues':['Unknown target segment asserted as a fact']} if purpose=='verify_brief' else {'en':section.copy(),'ru':section.copy()}
        monkeypatch.setattr(pipeline.llm,'complete',complete)
        with pytest.raises(ValueError,match='withheld'):generate_brief(db,j,ws)
        assert not items(db,wid,'brief')
        assert any(s['name']=='brief_correction_review' and s['status']=='withheld' for s in j.steps)


def test_queued_briefs_deduplicate_by_period_and_role(client):
    from app.pipeline import create_job
    owner=register(client);wid=workspace(client)
    with DB() as db:
        day=create_job(db,wid,owner['id'],'brief',{'period':'day','decision_role':'ceo'})
        week=create_job(db,wid,owner['id'],'brief',{'period':'week','decision_role':'ceo'})
        month=create_job(db,wid,owner['id'],'brief',{'period':'month','decision_role':'ceo'})
        duplicate=create_job(db,wid,owner['id'],'brief',{'period':'day','decision_role':'ceo'})
        assert len({day.id,week.id,month.id})==3
        assert duplicate.id==day.id


def test_quiet_brief_does_not_invent_market_calm(client):
    from app.pipeline import generate_brief
    owner=register(client);wid=workspace(client)
    with DB() as db:
        ws=db.get(Workspace,wid)
        j=Job(workspace_id=wid,user_id=owner['id'],kind='brief',input={'period':'day'});db.add(j);db.commit()
        generate_brief(db,j,ws);db.commit()
        b=items(db,wid,'brief')[0].payload
        assert b['quiet_period'] and b['event_count']==0 and not b['event_ids']
        assert 'not confirmation' in b['en']['executive_summary']


def test_scheduled_empty_brief_emails_only_verified_opted_in_role(client):
    owner=register(client);wid=workspace(client)
    with DB() as db:
        u=db.get(User,owner['id']);u.verified=True;u.preferences={'locale':'ru','email_briefs':True}
        ws=db.get(Workspace,wid)
        j=Job(workspace_id=wid,user_id=u.id,kind='brief',input={'period':'day','scheduled':True,'decision_role':'ceo'});db.add(j);db.commit()
        generate_brief(db,j,ws);db.commit()
        mail=items(db,wid,'mail')
        assert len(mail)==1 and 'нет новых проверенных' in mail[0].payload['subject']
        assert 'lang="ru"' in mail[0].payload['html'] and 'Открыть SignalDesk' in mail[0].payload['html']
        j2=Job(workspace_id=wid,user_id=u.id,kind='brief',input={'period':'week','scheduled':True,'decision_role':'cfo'});db.add(j2);db.commit()
        generate_brief(db,j2,ws);db.commit()
        assert len(items(db,wid,'mail'))==1


def test_russian_registration_and_reset_email_locale(client):
    r=client.post('/api/auth/register',json={'name':'Аналитик','email':'ru@example.invalid','password':'correct-test-password-123'},headers={'Accept-Language':'ru-RU,ru;q=0.9'})
    assert r.status_code==200 and r.json()['preferences']['locale']=='ru'
    assert client.post('/api/auth/reset-request',json={'email':'ru@example.invalid'}).status_code==200
    with DB() as db:
        mail=items(db,'auth','mail')
        assert len(mail)==2 and all('lang="ru"' in m.payload['html'] for m in mail)


def test_brief_schedules_are_independent_of_automatic_collection(client,monkeypatch):
    import app.pipeline as pipeline
    class MondayFirst(datetime):
        @classmethod
        def now(cls,tz=None):
            return cls(2026,6,1,8,tzinfo=timezone.utc)
    monkeypatch.setattr(pipeline,'datetime',MondayFirst)
    owner=register(client);wid=workspace(client)
    with DB() as db:
        ws=db.get(Workspace,wid);ws.onboarded=True
        ws.settings={**ws.settings,'auto_monitor':False,'scheduled_briefs':['day','week','month']}
        u=User(email='treasury@example.invalid',name='Treasury',password='unused');db.add(u);db.flush()
        db.add(Member(workspace_id=wid,user_id=u.id,role='viewer',decision_role='cfo'));db.commit()
        pipeline.scheduler_tick(db)
        jobs=db.query(Job).filter_by(workspace_id=wid).all()
        assert len(jobs)==6 and all(j.kind=='brief' for j in jobs)
        assert {(j.input['period'],j.input['decision_role']) for j in jobs}=={(p,r) for p in ['day','week','month'] for r in ['ceo','cfo']}
        pipeline.scheduler_tick(db)
        assert db.query(Job).filter_by(workspace_id=wid).count()==6


def test_public_socket_connects_only_to_validated_numeric_ip(monkeypatch):
    import socket,httpcore
    from app.network import PublicNetworkBackend
    seen=[]
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('8.8.8.8',443))])
    monkeypatch.setattr(httpcore.SyncBackend,'connect_tcp',lambda self,host,port,**kwargs:seen.append(host) or object())
    PublicNetworkBackend().connect_tcp('a-public-host.example',443)
    assert seen==['8.8.8.8']


def test_draft_edits_do_not_change_published_company_context(client):
    register(client);wid=workspace(client)
    original={'name':'Steel Maker','website':'https://example.com','industry':'Steel','exposures':['Credit products'],'reviewed':True}
    assert client.put(f'/api/workspaces/{wid}/profile',json=original).status_code==200
    draft=client.put(f'/api/workspaces/{wid}/profile',json={'industry':'Education','customers':['Teachers']}).json()
    assert draft['profile']['industry']=='Steel'
    assert draft['draft_profile']['industry']=='Education'
    assert draft['profile']['version']==1
    confirmed=client.put(f'/api/workspaces/{wid}/profile',json={'reviewed':True}).json()
    assert confirmed['profile']['industry']=='Education' and confirmed['profile']['version']==2
    assert confirmed['draft_profile'] is None


def test_confirmed_regions_resolve_stale_website_geography_question(client):
    register(client);wid=workspace(client)
    p={'name':'EduHub','website':'https://example.com','industry':'Education media','exposures':['Reader demand'],'regions':['United States','Australia'],'unknowns':['Target customer geography and primary market regions','Actual revenue'],'reviewed':True}
    r=client.put(f'/api/workspaces/{wid}/profile',json=p)
    assert r.status_code==200 and r.json()['profile']['unknowns']==['Actual revenue']


def test_imported_source_metadata_cannot_override_record_identity(client):
    register(client);wid=workspace(client)
    with DB() as db:
        row=record(db,wid,'source',{'id':'discovery-lead','name':'Imported primary source','url':'https://example.com/feed','type':'rss'})
        sid=row.id;db.commit()
    source=client.get(f'/api/workspaces/{wid}/sources').json()[0]
    assert source['id']==sid
    assert client.patch(f'/api/workspaces/{wid}/sources/{sid}',json={'enabled':False}).status_code==200


def test_relevance_ranking_keeps_other_publishers_in_the_analysis_batch():
    from app.pipeline import diverse_news
    ranked=[{'id':str(i),'url':f'https://specialist.example/news/{i}'} for i in range(8)]+[{'id':'au','url':'https://regional.example/education'}]
    chosen=diverse_news(ranked)
    assert len(chosen)==6 and any(c['id']=='au' for c in chosen)
    assert chosen[0]['id']=='0' and chosen[1]['id']=='1'


def test_assistant_withholds_unsupported_cross_market_claims(client,monkeypatch):
    from app import main
    register(client);wid=workspace(client)
    calls=[]
    def complete(w,purpose,*a,**kw):
        calls.append(purpose)
        if purpose=='verify_follow_up':return {'supported':False,'issues':['US funding is incorrectly applied to Australia']}
        return {'interpretation':'ESSER expires in Australia','event_ids':[],'bank_ids':[],'follow_up':'Next?'}
    monkeypatch.setattr(main.llm,'complete',complete)
    r=client.post(f'/api/workspaces/{wid}/assistant',json={'question':'What should we report in Australia?'})
    assert r.status_code==503 and calls==['follow_up','verify_follow_up','repair_follow_up','verify_follow_up']
    with DB() as db:assert not items(db,wid,'message')


def test_assistant_resolves_only_workspace_evidence_aliases(client,monkeypatch):
    from app import main
    register(client);wid=workspace(client)
    with DB() as db:
        e=record(db,wid,'event',{'decision_role':'ceo','profile_version':1,'en':{'title':'Local reporting'},'article':{'url':'https://example.com/news','text':'Local news'}});eid=e.id;db.commit()
    def complete(w,purpose,*a,**kw):
        if purpose=='verify_follow_up':return {'supported':True,'issues':[]}
        return {'interpretation':'Check the original reporting in E1.','event_ids':[],'bank_ids':[],'follow_up':'Which assumption matters?'}
    monkeypatch.setattr(main.llm,'complete',complete)
    r=client.post(f'/api/workspaces/{wid}/assistant',json={'question':'What should we check?'})
    assert r.status_code==200 and r.json()['event_ids']==[eid]
    assert r.json()['answer']=='Check the original reporting in [1].'


def test_brief_list_uses_current_company_context_version(client):
    register(client);wid=workspace(client)
    with DB() as db:
        ws=db.get(Workspace,wid);ws.profile={'version':2}
        record(db,wid,'brief',{'period':'week','decision_role':'ceo','profile_version':1})
        current=record(db,wid,'brief',{'period':'week','decision_role':'ceo','profile_version':2});bid=current.id;db.commit()
    assert [b['id'] for b in client.get(f'/api/workspaces/{wid}/briefs').json()]==[bid]


def test_job_trace_exposes_period_without_arbitrary_internal_inputs(client):
    from app.main import job_public
    j=Job(id='trace-test',workspace_id='test',kind='brief',input={'period':'week','decision_role':'cfo','internal_secret':'hidden'})
    public=job_public(j)
    assert public['input']=={'period':'week','decision_role':'cfo'}


def test_editorial_question_does_not_pull_unrelated_bank_research(client,monkeypatch):
    from app import main
    register(client);wid=workspace(client)
    with DB() as db:
        ws=db.get(Workspace,wid);ws.profile={'industry':'Education media','regions':['Australia'],'exposures':['Reader demand']};db.commit()
    def forbidden(*a,**k):raise AssertionError('Unrelated bank research should not be retrieved')
    monkeypatch.setattr(main,'retrieve_bank',forbidden)
    def complete(w,purpose,*a,**kw):
        if purpose=='verify_follow_up':return {'supported':True,'issues':[]}
        return {'interpretation':'No verified local article is available yet. Collect Australian reporting before choosing a topic.','event_ids':[],'bank_ids':[]}
    monkeypatch.setattr(main.llm,'complete',complete)
    assert client.post(f'/api/workspaces/{wid}/assistant',json={'question':'Separate the Australian source fact from one suggested editorial test.'}).status_code==200


def test_assistant_quotes_verified_fact_with_its_publisher_not_a_new_model_fact(client,monkeypatch):
    from app import main
    register(client);wid=workspace(client)
    fact='The Educator reports a Queensland school using Key Word Sign.'
    with DB() as db:
        record(db,wid,'event',{'decision_role':'ceo','profile_version':1,'en':{'fact':fact},'article':{'source_name':'The Educator','url':'https://example.com/queensland'}});db.commit()
    def complete(w,purpose,*a,**kw):
        if purpose=='verify_follow_up':return {'supported':True,'issues':[]}
        return {'interpretation':'If readers value practical inclusion tools, this suggests an editorial opportunity.','reported_fact':'The client implemented Key Word Sign.','event_ids':['E1'],'bank_ids':[],'next_step':'Test reader interest with a short pilot article.','uncertainties':['Reader engagement is unknown.']}
    monkeypatch.setattr(main.llm,'complete',complete)
    result=client.post(f'/api/workspaces/{wid}/assistant',json={'question':'Which Australian editorial test is supported?'}).json()
    assert f'Source [1] (The Educator): {fact}' in result['answer']
    assert 'The client implemented' not in result['answer'] and 'reported_fact' not in result
    assert 'Suggested next step: Test reader interest' in result['answer']


def test_malformed_assistant_structure_is_withheld_instead_of_crashing(client,monkeypatch):
    from app import main
    register(client);wid=workspace(client)
    monkeypatch.setattr(main.llm,'complete',lambda *a,**k:{'interpretation':'A conditional opportunity','uncertainties':None,'event_ids':[],'bank_ids':[]})
    r=client.post(f'/api/workspaces/{wid}/assistant',json={'question':'What should we investigate?'})
    assert r.status_code==503 and 'completeness' in r.json()['detail']
    with DB() as db:assert not items(db,wid,'message')
