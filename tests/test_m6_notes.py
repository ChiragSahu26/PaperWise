import time
import pytest
from fastapi.testclient import TestClient
import config
from app.main import app
from app.db.session import connect
from app.jobs.queue import now

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);monkeypatch.setattr(config,'OLLAMA_URL','http://127.0.0.1:1')
    with TestClient(app) as c:
        with connect() as db:
            db.execute("INSERT INTO documents(id,filename,file_path,file_type,status,title,added_at,page_count) VALUES (?,?,?,?,?,?,?,?)",('d','p.pdf','/tmp/nonexistent','pdf','ready','A paper',now(),3))
            db.execute("INSERT INTO chats(id,title,created_at,updated_at) VALUES ('chat','Chat',?,?)",(now(),now()))
            db.execute("INSERT INTO messages(id,chat_id,role,content,created_at) VALUES ('m','chat','assistant','Some answer',?)",(now(),))
        yield c

def test_notes_crud_fts_tags_export_anchors_and_deletion(client):
    payload={'body_md':'A precise finding about **orchid models**.','tags':['research','orchid'],
             'doc_id':'d','chat_id':'chat','message_id':'m','anchor':{'page':2,'bboxes':[[1,2,20,12]],'quote':'quoted text'}}
    r=client.post('/api/v1/notes',json=payload);assert r.status_code==200,r.text
    note=r.json();nid=note['id'];assert note['anchor']['page']==2
    assert [x['id'] for x in client.get('/api/v1/notes',params={'q':'precise orchid','tag':'research','doc_id':'d'}).json()]==[nid]
    assert [x['id'] for x in client.get('/api/v1/notes',params={'q':'research'}).json()]==[nid]
    assert client.patch('/api/v1/notes/'+nid,json={'body_md':'New evidence about water','tags':['climate']}).json()['body_md']=='New evidence about water'
    assert client.get('/api/v1/notes',params={'q':'orchid'}).json()==[]
    assert client.get('/api/v1/notes',params={'q':'climate'}).json()[0]['id']==nid
    assert 'New evidence about water' in client.get('/api/v1/notes/export?format=md').text
    assert client.delete('/api/v1/documents/d').status_code==200
    removed=client.get('/api/v1/notes').json()[0];assert removed['doc_id'] is None and removed['anchor'] is None
    assert client.delete('/api/v1/notes/'+nid).json()=={'ok':True}
    assert client.get('/api/v1/notes',params={'q':'water'}).json()==[]

def test_note_invalid_refs_and_anchor(client):
    assert client.post('/api/v1/notes',json={'body_md':'x','doc_id':'missing'}).status_code==404
    assert client.post('/api/v1/notes',json={'body_md':'x','anchor':{'page':1}}).status_code==422
    assert client.post('/api/v1/notes',json={'body_md':'x','doc_id':'d','anchor':{'page':10}}).status_code==422
    assert client.post('/api/v1/notes',json={'body_md':'x','doc_id':'d','anchor':{'page':1,'bboxes':[[5,5,3,3]]}}).status_code==422

@pytest.mark.usefixtures('embedding_model_cached')
def test_opt_in_notes_retrieval_and_scope(client):
    from app.core.retrieval.search import retrieve
    note=client.post('/api/v1/notes',json={'body_md':'A surprising orchid pollination discovery was recorded.','doc_id':'d'}).json()
    assert retrieve('orchid pollination discovery',['d'],mode='semantic')['retrieved']==[]
    client.put('/api/v1/settings',json={'notes_in_retrieval':True})
    for _ in range(200):
        result=retrieve('orchid pollination discovery',['d'],mode='semantic')['retrieved']
        if result:break
        time.sleep(.05)
    assert result and result[0]['chunk']['id']=='note:'+note['id'] and result[0]['chunk']['title']=='Your note'
    client.put('/api/v1/settings',json={'notes_in_retrieval':False})
    assert retrieve('orchid pollination discovery',['d'],mode='semantic')['retrieved']==[]

def test_fts_migration_indexes_preexisting_notes(tmp_path,monkeypatch):
    from app.db.session import connect,initialize,SCHEMA
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    with connect() as db:
        db.executescript(SCHEMA.read_text())
        db.execute("INSERT INTO notes(id,body_md,tags_json,created_at,updated_at) VALUES ('old','Legacy orbital analysis','[\"cosmos\"]',?,?)",(now(),now()))
    initialize();initialize()
    from app.api.notes import note_query
    assert note_query(q='orbital')[0]['id']=='old' and note_query(q='cosmos')[0]['id']=='old'

def test_openapi_includes_m3_to_m6_contracts(client):
    paths=client.get('/openapi.json').json()['paths']
    for path in ['/api/v1/chats/check-duplicate','/api/v1/chats/{chat_id}/similar','/api/v1/topics',
                 '/api/v1/documents/{doc_id}/intelligence','/api/v1/documents/{doc_id}/resources','/api/v1/notes']:
        assert path in paths
