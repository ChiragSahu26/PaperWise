import asyncio,json,time
import pytest
from fastapi.testclient import TestClient
import config
from app.main import app
from app.db.session import connect
from app.jobs.queue import now
from app.core.checks.faithfulness import nli_probabilities, sentence_spans,check_answer

@pytest.mark.usefixtures('nli_model_cached')
def test_real_local_nli_and_offsets():
    scores=nli_probabilities([('The model scored 92 percent on the test set.','The model scored 92 percent on the test set.'),('The model scored 92 percent on the test set.','The model scored 3 percent on the test set.')])
    assert scores[0]>.7 and scores[1]<.35
    md='## Results\n| Accuracy | Reported value |\n|---|---|\n| Accuracy | 92 percent [1] |\n'
    spans=sentence_spans(md)
    assert any(s=='92 percent [1]' and md[a:b]==s for a,b,s in spans)

@pytest.mark.asyncio
async def test_faithfulness_fallback_and_persistence(tmp_path,monkeypatch):
    from app.db.session import initialize
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);initialize()
    answer='The model reports 92 percent [1].'
    with connect() as db:
        db.execute("INSERT INTO chats(id,created_at,updated_at) VALUES ('chat',?,?)",(now(),now()))
        db.execute("INSERT INTO messages(id,chat_id,role,content,created_at,debug_json) VALUES ('m','chat','assistant',?,?,?)",(answer,now(),json.dumps({'retrieved':[{'chunk_id':'c','text':'The model reports 92 percent.'}]})))
    def unavailable(_):raise RuntimeError('no weights')
    monkeypatch.setattr('app.core.checks.faithfulness.nli_probabilities',unavailable)
    class Judge:
        async def background_complete(self,prompt,**kwargs):return '{"label":"supported"}'
    result=await check_answer(Judge(),'m')
    assert result['sentences'][0]['label']=='supported'
    s=result['sentences'][0];assert answer[s['start']:s['end']]==answer and s['chunk_ids']==['c']
    with connect() as db:assert json.loads(db.execute("SELECT faithfulness_json FROM messages WHERE id='m'").fetchone()[0])==result['sentences']

def test_similarity_api_job_modes_exact_offsets_quote_and_exclusion(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);monkeypatch.setattr(config,'OLLAMA_URL','http://127.0.0.1:1')
    text='The remarkable orchid experiment achieved consistent accuracy across several independent validation datasets.'
    with TestClient(app) as c:
        with connect() as db:
            for doc in ('one','two'):
                db.execute('INSERT INTO documents(id,filename,file_path,file_type,status,title,added_at) VALUES (?,?,?,?,?,?,?)',(doc,doc+'.txt','/tmp/no','txt','ready',doc,now()))
                db.execute('INSERT INTO chunks(id,doc_id,type,text,location_label,segment_index,char_start,char_end) VALUES (?,?,?,?,?,?,?,?)',('c'+doc,doc,'text',text,'Part 1',0,0,len(text)))
        writing='"'+text+'" '+text
        created=c.post('/api/v1/similarity-checks',json={'mode':'my_writing','text':writing,'exclude_quotes':True}).json()
        for _ in range(100):
            job=c.get('/api/v1/jobs/'+created['job_id']).json()
            if job['status'] in ('done','failed'):break
            time.sleep(.05)
        assert job['status']=='done',job
        report=c.get('/api/v1/similarity-checks/'+created['check_id']).json()
        assert report['overall_percent']==100 and len(report['matches'])==1
        m=report['matches'][0];assert m['kind']=='exact' and writing[m['text_span']['start']:m['text_span']['end']]==text
        created=c.post('/api/v1/similarity-checks',json={'mode':'corpus','doc_id':'one'}).json()
        for _ in range(100):
            job=c.get('/api/v1/jobs/'+created['job_id']).json()
            if job['status'] in ('done','failed'):break
            time.sleep(.05)
        assert job['status']=='done',job
        report=c.get('/api/v1/similarity-checks/'+created['check_id']).json()
        assert report['matches'][0]['source_doc_id']=='two'
        assert c.post('/api/v1/similarity-checks',json={'mode':'web'}).json()['error']['code']=='ONLINE_FEATURE_DISABLED'

def test_paraphrase_branch(tmp_path,monkeypatch):
    from app.db.session import initialize
    from app.core.checks.similarity import run_check
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);initialize()
    monkeypatch.setattr('app.core.checks.similarity.embed',lambda texts:[[1.,0.] for _ in texts])
    target='A different wording explains how a scientific model reached strong evaluation results.'
    source='Our experimental methodology demonstrates reliable outcomes across multiple benchmark datasets today.'
    with connect() as db:
        db.execute("INSERT INTO documents(id,filename,file_path,file_type,status,added_at) VALUES ('d','p.txt','/tmp/no','txt','ready',?)",(now(),))
        db.execute("INSERT INTO chunks(id,doc_id,type,text,location_label) VALUES ('c','d','text',?,'Part 1')",(source,))
        db.execute("INSERT INTO similarity_checks(id,scope,created_at) VALUES ('r','my_writing',?)",(now(),))
    result=run_check('r',{'text':target,'doc_id':None,'scope':'my_writing','exclude_quotes':False})
    assert result['matches'][0]['kind']=='paraphrase' and result['matches'][0]['similarity']==1
