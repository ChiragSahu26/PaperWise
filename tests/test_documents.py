import sys, time, types
import pytest
from fastapi.testclient import TestClient
import config
from app.main import app

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    monkeypatch.setattr(config,'OLLAMA_URL','http://127.0.0.1:1')
    # Deterministic vectors keep this queue/API test independent of model weights.
    from app.core.retrieval import vector_store
    monkeypatch.setattr(vector_store,'embed',lambda texts:[[1.0,0.0] for _ in texts])
    with TestClient(app) as client: yield client

def wait_ready(client,doc_id):
    for _ in range(100):
        row=client.get(f'/api/v1/documents/{doc_id}').json()
        if row['status'] in ('ready','failed'): return row
        time.sleep(.02)
    pytest.fail('ingestion timed out')

def test_upload_duplicate_delete_and_file_range(client):
    text=b'This is the main research document with an accurate result.'
    result=client.post('/api/v1/documents',files={'files':('a.txt',text,'text/plain')})
    assert result.status_code==200, result.text
    doc_id=result.json()[0]['doc_id']; assert result.json()[0]['status']=='queued'
    assert wait_ready(client,doc_id)['status']=='ready'
    assert client.get('/api/v1/documents').json()[0]['id']==doc_id
    dup=client.post('/api/v1/documents',files={'files':('other.txt',text,'text/plain')}).json()[0]
    assert dup['doc_id']==doc_id and dup['warning']
    assert client.get(f'/api/v1/documents/{doc_id}/file',headers={'Range':'bytes=0-3'}).content == text[:4]
    assert client.get(f'/api/v1/documents/{doc_id}/chunks/{doc_id}:0:0').json()['text']==text.decode()
    assert client.delete(f'/api/v1/documents/{doc_id}').json()['ok']
    assert client.get(f'/api/v1/documents/{doc_id}').status_code==404

def test_invalid_file(client):
    r=client.post('/api/v1/documents',files={'files':('fake.pdf',b'hello','application/pdf')})
    assert r.status_code==400 and r.json()['error']['code']=='UNSUPPORTED_FILE'
