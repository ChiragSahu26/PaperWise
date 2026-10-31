import pytest
import time, json
from fastapi.testclient import TestClient
import config
from app.main import app

class FakeLLM:
    async def stream(self,messages,**kwargs):
        assert 'Orchid experiments achieved 95 percent accuracy.' in messages[1]['content']
        yield 'The reported accuracy was '
        yield '95 percent [1].'

@pytest.mark.usefixtures("embedding_model_cached")
def test_end_to_end_upload_retrieve_and_stream(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    monkeypatch.setattr(config,'OLLAMA_URL','http://127.0.0.1:1')
    app.state.llm_provider=FakeLLM()
    with TestClient(app) as client:
        client.put('/api/v1/settings',json={'use_reranker':False})
        r=client.post('/api/v1/documents',files={'files':('paper.txt',b'Orchid experiments achieved 95 percent accuracy.','text/plain')})
        doc=r.json()[0]['doc_id']
        for _ in range(300):
            status=client.get('/api/v1/documents/'+doc).json()['status']
            if status in ('ready','failed'):break
            time.sleep(.05)
        assert status=='ready'
        chat=client.post('/api/v1/chats',json={'doc_ids':[doc]}).json()['id']
        out=client.post(f'/api/v1/chats/{chat}/messages',json={'question':'What is the orchid accuracy?'}).text
        entries=[]
        for block in out.strip().split('\n\n'):
            lines=block.splitlines()
            if len(lines)>1 and lines[0].startswith('event: '): entries.append((lines[0][7:],json.loads(lines[1][6:])))
        assert [x[0] for x in entries[:6]] == ['retrieval','citations','token','token','confidence','done']
        assert all(x[0]=='faithfulness' for x in entries[6:])
        if len(entries)>6: assert entries[6][1]['message_id']==entries[0][1]['message_id']
        mid=entries[0][1]['message_id']
        answer=client.get(f'/api/v1/chats/{chat}/messages/{mid}').json()
        assert answer['citations'][0]['doc_id']==doc and answer['citations'][0]['cited']
        assert answer['content']=='The reported accuracy was 95 percent [1].'
        if len(entries)>6: assert answer['faithfulness']==entries[6][1]['sentences']
