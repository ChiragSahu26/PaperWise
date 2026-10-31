import time,uuid
import pytest
from fastapi.testclient import TestClient
import config
from app.main import app
from app.jobs.queue import now
from app.db.session import connect
from app.core.chats.similar import index_question,update_chat_vector

QUESTIONS=[
('biology','How do convolutional neural networks classify medical X-ray images of lung disease?'),
('biology','How can convolutional neural networks identify lung disease from medical X-ray images?'),
('biology','How do convolutional neural networks detect pneumonia in medical chest X-ray images?'),
('biology','How does deep learning classify lung diseases in medical chest X-ray images?'),
('climate','How do climate models predict future global warming and temperature change?'),
('climate','How can climate models forecast future global warming and temperature change?'),
('climate','How do scientists model future global warming and climate temperature changes?'),
('quantum','How do quantum computers use qubits for quantum computing algorithms?'),
('quantum','How are qubits used in quantum computing algorithms on quantum computers?'),
('quantum','How do quantum computing algorithms run using qubits on quantum computers?')]
class TopicLLM:
    async def stream(self,messages,**kwargs):
        yield 'Related Research Topics'

@pytest.mark.usefixtures('embedding_model_cached')
def test_ten_chats_three_topics_and_duplicate(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);monkeypatch.setattr(config,'OLLAMA_URL','http://127.0.0.1:1')
    app.state.llm_provider=TopicLLM(); labels={}; ids=[]
    with TestClient(app) as client:
        for label,question in QUESTIONS:
            cid=client.post('/api/v1/chats',json={'title':question[:40],'doc_ids':[]}).json()['id']
            mid=str(uuid.uuid4());labels[cid]=label;ids.append((cid,mid,question))
            with connect() as db:
                db.execute('INSERT INTO messages(id,chat_id,role,content,created_at) VALUES (?,?,?,?,?)',(mid,cid,'user',question,now()))
            index_question(cid,mid,question);update_chat_vector(cid)
        matches=0
        for cid,_,_ in ids:
            result=client.get(f'/api/v1/chats/{cid}/similar').json()
            if result and labels[result[0]['chat_id']]==labels[cid]:matches+=1
        assert matches>=8, f'only {matches}/10 nearest neighbors matched topics'
        repeat=client.post('/api/v1/chats/check-duplicate',json={'question':ids[0][2]}).json()['match']
        assert repeat and repeat['message_id']==ids[0][1] and repeat['similarity']>=.9
        other=client.get('/api/v1/chats/'+ids[0][0]+'/similar').json()[0]['chat_id']
        assert client.post(f'/api/v1/chats/{ids[0][0]}/similar/dismiss',json={'other_chat_id':other}).json()['ok']
        assert other not in [x['chat_id'] for x in client.get(f'/api/v1/chats/{ids[0][0]}/similar').json()]
        assert ids[0][0] not in [x['chat_id'] for x in client.get(f'/api/v1/chats/{other}/similar').json()]
        job=client.post('/api/v1/topics/recompute').json()['job_id']
        for _ in range(200):
            state=client.get('/api/v1/jobs/'+job).json()
            if state['status'] in ('done','failed'):break
            time.sleep(.05)
        assert state['status']=='done',state
        topics=client.get('/api/v1/topics').json()
        assert topics and all(len(x['chat_ids'])>1 and x['label']=='Related Research Topics' for x in topics)
