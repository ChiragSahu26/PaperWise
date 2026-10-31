import json,time
from datetime import date
import pytest
from fastapi.testclient import TestClient
import config
from app.main import app
from app.db.session import connect
from app.jobs.queue import now
from app.core.intelligence import online
from app.core.intelligence.resolve import evidence

class LLM:
    async def stream(self,messages,**kwargs):
        yield json.dumps({'concepts':[{'name':'Optical thermometry','why':'Core measurement'}, {'name':'Quantum sensors','why':'Method'}, {'name':'Living cells','why':'Application'}]})

def seed():
    with connect() as db:
        db.execute("INSERT INTO documents(id,filename,file_path,file_type,status,title,authors_json,abstract,doi,arxiv_id,added_at,page_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   ('d','p.pdf','/tmp/no','pdf','ready','Nanometer scale thermometry in a living cell','["Alice Smith"]','Optical thermometry and quantum sensors.','10.1038/nature12373','arXiv:1304.1068',now(),1))
        db.execute("INSERT INTO chunks(id,doc_id,text,location_label,page,bboxes_json) VALUES ('k','d','Published: 2013-07-30 https://github.com/octocat/Hello-World','Page 1',1,'[[1,2,3,4]]')")

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);monkeypatch.setattr(config,'OLLAMA_URL','http://127.0.0.1:1')
    app.state.llm_provider=LLM()
    with TestClient(app) as c:seed();yield c

def test_offline_intelligence_no_network(client,monkeypatch):
    async def never(*args,**kwargs):raise AssertionError('internet call while disabled')
    monkeypatch.setattr(online,'get_json',never)
    res=client.get('/api/v1/documents/d/intelligence')
    assert res.status_code==200 and res.json()['online'] is False and res.json()['doi']=='10.1038/nature12373'
    assert res.json()['published']=='2013-07-30'
    try: __import__('asyncio').run(online.get_json('https://api.crossref.org/works'))
    except AssertionError: pass # patched only to prove the endpoint did not call it
    response=client.get('/api/v1/documents/d/resources');assert response.json()['status']=='pending'
    for _ in range(100):
        data=client.get('/api/v1/documents/d/resources').json()
        if data['status']=='ready':break
        time.sleep(.05)
    assert len(data['concepts'])==3 and all(c['items'][0]['url'].startswith('https://www.youtube.com/results?') for c in data['concepts'])

def test_intelligence_known_doi_with_provider_mocks(client,monkeypatch):
    async def fake(url,**kw):
        if 'semanticscholar' in url:return {'title':'Nanometer scale thermometry in a living cell','venue':'Nature','publicationDate':'2013-07-30','citationCount':1839,'influentialCitationCount':195,'externalIds':{'ArXiv':'1304.1068'},'authors':[{'name':'Alice Smith'}],'publicationTypes':['JournalArticle']}
        if 'openalex' in url:return {'id':'https://openalex.org/W1','type':'article','is_retracted':False,'counts_by_year':[{'year':date.today().year,'cited_by_count':31},{'year':date.today().year-1,'cited_by_count':42}]}
        if 'crossref.org/works/' in url:return {'message':{'type':'journal-article','container-title':['Nature']}}
        if 'crossref.org/works' in url:return {'message':{'items':[]}}
        if 'github' in url:return {'stargazers_count':100,'pushed_at':'2026-01-03T00:00:00Z'}
        if 'huggingface' in url:return {'id':'1304.1068'}
        raise AssertionError(url)
    monkeypatch.setattr(online,'get_json',fake)
    client.put('/api/v1/settings',json={'online_lookups':True})
    res=client.get('/api/v1/documents/d/intelligence?refresh=true')
    assert res.status_code==200,res.text
    obj=res.json();assert obj['online'] and obj['identified'] and obj['title'] and obj['venue']=='Nature'
    assert obj['citations']['total']==1839 and obj['citations']['last_12_months']==73
    assert obj['code'][0]['stars']==100 and obj['trending']['huggingface'] is True
    assert {'age_adjusted_citations','influential_ratio','peer_review','retraction'}=={p['name'] for p in obj['evidence_strength']['parts']}
    assert client.get('/api/v1/documents').json()[0]['intelligence_badge']['age_bucket']=='older'
    client.put('/api/v1/settings',json={'online_lookups':False})
    assert client.get('/api/v1/documents/d/intelligence').json()['online'] is False

def test_evidence_retraction_override():
    result=evidence(500,100,'2025-01-01','journal',True)
    assert result['level']=='low' and result['note']=='A guide, not a verdict on quality.'

@pytest.mark.asyncio
async def test_disabled_wrapper_and_retry_after(tmp_path,monkeypatch):
    from app.db.session import initialize
    from app.errors import PaperWiseError
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);initialize()
    with pytest.raises(PaperWiseError) as e:await online.get_json('https://api.crossref.org/works')
    assert e.value.code=='ONLINE_FEATURE_DISABLED'
    assert online.delay_for('2',0)==2 and online.delay_for(None,2)==6

def test_crossref_updated_by_retraction_overrides(client,monkeypatch):
    async def fake(url,**kw):
        if 'semanticscholar' in url:return {'title':'Paper','publicationDate':'2019-01-01','citationCount':500,'influentialCitationCount':100,'publicationTypes':['JournalArticle']}
        if 'openalex' in url:return {'id':'https://openalex.org/W1','type':'article','is_retracted':False}
        if 'crossref.org/works/' in url:return {'message':{'updated-by':[{'type':'retraction','DOI':'10.1234/notice'}]}}
        if 'crossref.org/works' in url:return {'message':{'items':[]}}
        if 'github' in url:return {}
        raise online.OnlineNotFound()
    monkeypatch.setattr(online,'get_json',fake)
    client.put('/api/v1/settings',json={'online_lookups':True})
    obj=client.get('/api/v1/documents/d/intelligence?refresh=true').json()
    assert obj['retraction']=={'retracted':True,'notice_url':'https://doi.org/10.1234/notice'}
    assert obj['evidence_strength']['level']=='low'

@pytest.mark.asyncio
async def test_online_http_retry_cache_and_opt_out(tmp_path,monkeypatch):
    import httpx
    from app.db.session import initialize
    from app.errors import PaperWiseError
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);monkeypatch.setattr(config,'API_RETRIES',1);initialize()
    with connect() as db:db.execute("INSERT INTO settings(key,value_json) VALUES ('online_lookups','true')")
    calls=[];delays=[];original=httpx.AsyncClient
    def handler(request):
        calls.append(request)
        assert request.headers['user-agent'].startswith('PaperWise/2.0')
        if len(calls)==1:return httpx.Response(429,headers={'Retry-After':'2'})
        return httpx.Response(200,json={'ok':True})
    monkeypatch.setattr(online.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    async def sleep(value):delays.append(value)
    monkeypatch.setattr(online.asyncio,'sleep',sleep)
    url='https://api.crossref.org/works/10.1000/example'
    assert await online.get_json(url)=={'ok':True} and delays==[2]
    assert await online.get_json(url)=={'ok':True} and len(calls)==2
    with connect() as db:db.execute("UPDATE settings SET value_json='false' WHERE key='online_lookups'")
    with pytest.raises(PaperWiseError) as exc:await online.get_json(url)
    assert exc.value.code=='ONLINE_FEATURE_DISABLED'
