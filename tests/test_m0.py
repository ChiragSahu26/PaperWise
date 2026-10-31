import sqlite3
import pytest
from fastapi.testclient import TestClient
import config
from app.main import app

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config, 'OLLAMA_URL', 'http://127.0.0.1:1')
    with TestClient(app) as c:
        yield c

def test_offline_health(client):
    data = client.get('/api/v1/health').json()
    assert data['status'] == 'ok' and data['ollama'] == {'up':False,'models':[]}
    assert data['online_lookups_enabled'] is False and data['device'] in ('cpu','mps')

def test_models_unavailable(client):
    r=client.get('/api/v1/models')
    assert r.status_code==503 and r.json()['error']['code']=='OLLAMA_UNAVAILABLE'

def test_settings_persist_and_validate(client):
    assert client.put('/api/v1/settings',json={'top_k':9,'hybrid_weights':{'semantic':0.5,'bm25':0.5}}).json()['top_k']==9
    assert client.get('/api/v1/settings').json()['top_k']==9
    assert client.put('/api/v1/settings',json={'top_k':21}).json()['error']['code']=='VALIDATION_ERROR'
    assert client.put('/api/v1/settings',json={'hybrid_weights':{'semantic':0.8,'bm25':0.5}}).status_code == 422
    assert client.put('/api/v1/settings',json={'top_k':None}).status_code == 422
    assert client.put('/api/v1/settings',json={'unrecognised':True}).status_code == 422
    assert client.get('/api/v1/settings').json()['top_k']==9

def test_sqlite_schema_and_restart(client):
    from app.db.session import initialize
    initialize()
    db=sqlite3.connect(config.DATA_DIR/'paperwise.sqlite3')
    assert db.execute('pragma journal_mode').fetchone()[0]=='wal'
    assert {'documents','chunks','chats','messages','settings'} <= {r[0] for r in db.execute("select name from sqlite_master where type='table'")}

def test_404_format(client):
    r=client.get('/no-such-endpoint')
    assert r.status_code==404 and r.json()['error']['code']=='NOT_FOUND'
