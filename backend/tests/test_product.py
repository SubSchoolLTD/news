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


def test_demo_workspaces_are_isolated_and_labelled(client):
    a=client.post('/api/demo',json={'variant':'industrial'}).json();wid=a['workspace_id']
    events=client.get(f'/api/workspaces/{wid}/events').json()
    assert len(events)==8 and all(e['is_demo'] for e in events)
    b=TestClient(app);other=b.post('/api/demo',json={'variant':'subschool'}).json()
    assert other['workspace_id']!=wid
    assert b.get(f'/api/workspaces/{wid}/events').status_code==404
    education=b.get(f"/api/workspaces/{other['workspace_id']}/events").json()
    assert events[0]['en']['why']!=education[0]['en']['why']


def test_unsupported_ai_drafts_are_withheld(client,monkeypatch):
    from app import pipeline
    owner=register(client);wid=workspace(client)
    with DB() as db:
        ws=db.get(Workspace,wid);ws.onboarded=True;ws.profile={"industry":"Steel","exposures":["steel prices"],"version":1};ws.settings={"min_relevance":0}
        a=record(db,wid,'article',{"title":"Steel prices change","text":"Steel prices change with manufacturing demand.","published_at":now(),"url":"https://example.com/news","evidence_level":"feed"});aid=a.id
        j=Job(workspace_id=wid,user_id=owner['id'],kind='analyze',status='running',input={});db.add(j);db.commit()
        monkeypatch.setattr(pipeline,'collect_sources',lambda s:([],[]))
        def complete(ws,purpose,prompt,**kwargs):
            if purpose=='analysis_plan':return {"research_query":"steel prices","missing_data":[]}
            if purpose=='interpret_events':return {"events":[{"article_id":aid,"en":{"title":"Unsupported"},"ru":{"title":"Unsupported"}}]}
            return {"reviews":[{"article_id":aid,"supported":False,"issues":["Invented company debt"]}]}
        monkeypatch.setattr(pipeline.llm,'complete',complete)
        run_analysis(db,j,ws);db.commit()
        assert not items(db,wid,'event')
        assert j.result['rejected']==1
        assert any(s['name']=='adapt' for s in j.steps)


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
