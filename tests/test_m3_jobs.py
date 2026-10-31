import time
import pytest
from fastapi.testclient import TestClient
import config
from app.main import app
from app.api import chats
from app.db.session import connect
from app.jobs.queue import now

class Provider:
    async def stream(self,messages,**kwargs):
        text=messages[0]['content']
        if text.startswith('Write a 3 to 6 word title'): yield 'Research Methods and Results'
        elif text.startswith('Write a one-line summary'): yield 'A discussion of research methods.'
        else: yield 'The method uses data [1].'

def fake_retrieval(question,doc_ids,top_k,compare):
    c={'id':'chunk','doc_id':'d','title':'Paper','filename':'paper.txt','text':'The method uses data.',
       'page':None,'location_label':'Part 1','bboxes':None}
    return {'expanded_query':question,'retrieved':[{'chunk':c,'hybrid_score':.8,'rerank_score':None,'cosine':.8,'rank':1}],
            'candidates':1,'reranked':False,'warnings':[]}

@pytest.mark.usefixtures('embedding_model_cached')
def test_title_summary_embedding_and_export_jobs(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);monkeypatch.setattr(config,'OLLAMA_URL','http://127.0.0.1:1')
    monkeypatch.setattr(chats,'get_retrieval',fake_retrieval)
    app.state.llm_provider=Provider()
    with TestClient(app) as client:
        with connect() as db:
            db.execute("INSERT INTO documents(id,filename,file_path,file_type,status,title,added_at) VALUES ('d','paper.txt','/tmp/no','txt','ready','Paper',?)",(now(),))
            db.execute("INSERT INTO chunks(id,doc_id,text,location_label) VALUES ('chunk','d','The method uses data.','Part 1')")
        cid=client.post('/api/v1/chats',json={'doc_ids':['d']}).json()['id']
        response=client.post(f'/api/v1/chats/{cid}/messages',json={'question':'What methods are used?'})
        assert 'event: done' in response.text
        for _ in range(200):
            chat=client.get('/api/v1/chats/'+cid).json()
            dupe=client.post('/api/v1/chats/check-duplicate',json={'question':'What methods are used?'}).json()['match']
            with connect() as db: embedded=db.execute("SELECT 1 FROM jobs WHERE kind='chat_embed' AND status='done'").fetchone()
            if chat['summary'] and dupe and embedded:break
            time.sleep(.05)
        assert chat['title']=='Research Methods and Results'
        assert chat['summary']=='A discussion of research methods.'
        assert dupe and embedded
        markdown=client.get(f'/api/v1/chats/{cid}/export').text
        assert 'Date:' in markdown and 'Active documents: Paper' in markdown and '[1] Paper' in markdown
