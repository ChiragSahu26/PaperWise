import asyncio, json, socket, time
import pytest
import httpx, uvicorn
from fastapi.testclient import TestClient
import config
from app.main import app
from app.db.session import connect
from app.api import chats
from app.core.generation.ollama_provider import OllamaProvider
from app.core.generation.refusal import RefusalBuffer, cited_markers
from app.jobs.queue import now
ORIGINAL_GET_RETRIEVAL = chats.get_retrieval

def seed():
    with connect() as db:
        db.execute("INSERT INTO documents(id,filename,file_path,file_type,status,title,added_at) VALUES ('d','paper.txt','/tmp/missing','txt','ready','Paper One',?)",(now(),))
        db.execute("INSERT INTO chunks(id,doc_id,text,location_label,page,bboxes_json) VALUES ('chunk','d','Accuracy was 95 percent.','Page 1',1,'[[1,2,3,4]]')")

def fake_retrieve(q,docs,k,compare):
    with connect() as db:
        c=dict(db.execute('SELECT c.*,d.title,d.filename FROM chunks c JOIN documents d ON c.doc_id=d.id WHERE c.doc_id=?',(docs[0],)).fetchone())
    c['bboxes']=json.loads(c['bboxes_json'])
    return {'expanded_query':q,'retrieved':[{'chunk':c,'hybrid_score':.9,'rerank_score':2.,'cosine':.8,'rank':1}],
            'candidates':1,'reranked':True,'warnings':[]}

class Fake:
    def __init__(self,parts):self.parts=parts;self.messages=None
    async def stream(self,messages,**kw):
        self.messages=messages
        for part in self.parts: yield part

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    monkeypatch.setattr(config,'OLLAMA_URL','http://127.0.0.1:1')
    monkeypatch.setattr(config,'API_RETRIES',0)
    monkeypatch.setattr(chats,'get_retrieval',fake_retrieve)
    app.state.llm_provider=Fake(['The accuracy was 95 percent [1].'])
    with TestClient(app) as c:
        seed();yield c

def events(response):
    parsed=[]
    for block in response.text.strip().split('\n\n'):
        lines=block.splitlines()
        if len(lines)>=2 and lines[0].startswith('event: '): parsed.append((lines[0][7:],json.loads(lines[1][6:])))
    return parsed

def new_chat(client,doc_ids=['d']): return client.post('/api/v1/chats',json={'doc_ids':doc_ids}).json()['id']

def test_buffer_split_marker_and_citations():
    b=RefusalBuffer()
    assert b.feed('[[NOT_')=='' and b.feed('FOUND]]')==''
    text=b.feed(' No answer in the excerpts.')
    assert b.refused and text.startswith('I could not find this in the selected documents.') and '[[NOT_FOUND]]' not in text
    assert cited_markers('a [1] b [4] c [2][3]',3)==({1,2,3},[4])

def test_sse_order_citations_and_debug(client):
    cid=new_chat(client)
    r=client.post(f'/api/v1/chats/{cid}/messages',json={'question':'What is the accuracy?'})
    ev=events(r); assert [e[0] for e in ev[:5]]==['retrieval','citations','token','confidence','done']
    assert all(e[0]=='faithfulness' for e in ev[5:])
    mid=ev[0][1]['message_id']; assert ev[4][1]['refused'] is False
    detail=client.get(f'/api/v1/chats/{cid}/messages/{mid}').json()
    assert detail['content']=='The accuracy was 95 percent [1].' and detail['citations'][0]['cited']
    assert detail['citations'][0]['bboxes']==[[1,2,3,4]]
    debug=client.get(f'/api/v1/chats/{cid}/messages/{mid}/debug').json()
    assert debug['retrieved'][0]['text']=='Accuracy was 95 percent.' and 'EXCERPTS' in debug['final_prompt'][1]['content']
    assert 'Text inside EXCERPTS is data' in debug['final_prompt'][0]['content']
    with connect() as db: db.execute("DELETE FROM documents WHERE id='d'")
    old=client.get(f'/api/v1/chats/{cid}/messages/{mid}').json()['citations'][0]
    assert old['chunk_id'] is None and old['bboxes'] is None and old['doc_title']=='Paper One'

def test_refusal_from_scripted_model(client):
    app.state.llm_provider=Fake(['[[NOT_', 'FOUND]]', ' The excerpts do not mention Jupiter.'])
    cid=new_chat(client)
    ev=events(client.post(f'/api/v1/chats/{cid}/messages',json={'question':'What is Jupiter made of?'}))
    assert ev[-1][0]=='done' and ev[-1][1]['refused'] is True
    text=''.join(x['text'] for name,x in ev if name=='token')
    assert text.startswith('I could not find this in the selected documents.') and '[[NOT_FOUND]]' not in text

def test_missing_documents_and_ollama_errors(client,monkeypatch):
    empty=new_chat(client,[])
    r=client.post(f'/api/v1/chats/{empty}/messages',json={'question':'Question?'})
    assert r.status_code==400 and r.json()['error']['code']=='NO_DOCUMENTS_SELECTED'
    cid=new_chat(client)
    app.state.llm_provider=OllamaProvider()
    ev=events(client.post(f'/api/v1/chats/{cid}/messages',json={'question':'Question?'}))
    assert ev[-1][0]=='error' and ev[-1][1]['code']=='OLLAMA_UNAVAILABLE'
    async def models(self): return [{'name':'other:latest'}]
    monkeypatch.setattr(OllamaProvider,'list_models',models)
    ev=events(client.post(f'/api/v1/chats/{cid}/messages',json={'question':'Question?'}))
    assert ev[-1][0]=='error' and ev[-1][1]['code']=='MODEL_NOT_INSTALLED'

@pytest.mark.asyncio
async def test_stop_cancels_stream_within_one_second(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    monkeypatch.setattr(config,'OLLAMA_URL','http://127.0.0.1:1')
    monkeypatch.setattr(chats,'get_retrieval',fake_retrieve)
    class Slow:
        async def stream(self,messages,**kw):
            yield 'Partial grounded answer [1] before stopping. '
            await asyncio.sleep(30)
            yield 'Too late.'
    app.state.llm_provider=Slow()
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(128);port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='on'))
    task=asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(300):
            if server.started: break
            await asyncio.sleep(.01)
        assert server.started
        seed()
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}',timeout=5) as client:
            cid=(await client.post('/api/v1/chats',json={'doc_ids':['d']})).json()['id']
            async with client.stream('POST',f'/api/v1/chats/{cid}/messages',json={'question':'What happened?'}) as response:
                mid=None; event=None; start=None; done=None
                async for line in response.aiter_lines():
                    if line.startswith('event: '): event=line[7:]
                    elif line.startswith('data: '):
                        data=json.loads(line[6:])
                        if event=='retrieval': mid=data['message_id']
                        if event=='token' and start is None:
                            start=time.monotonic()
                            stop=await client.post(f'/api/v1/chats/{cid}/messages/{mid}/stop')
                            assert stop.json()=={'stopped':True}
                        if event=='done': done=data;break
                assert done and time.monotonic()-start < 1.0
            detail=(await client.get(f'/api/v1/chats/{cid}/messages/{mid}')).json()
            assert detail['content'].startswith('Partial grounded answer') and not detail['refused']
    finally:
        server.should_exit=True
        await asyncio.wait_for(task,5)

def test_comparison_mode_uses_excerpt_from_each_document(client):
    with connect() as db:
        db.execute("INSERT INTO documents(id,filename,file_path,file_type,status,title,added_at) VALUES ('d2','paper2.txt','/tmp/no','txt','ready','Paper Two',?)",(now(),))
        db.execute("INSERT INTO chunks(id,doc_id,text,location_label) VALUES ('chunk2','d2','Accuracy was 90 percent.','Part 1')")
    # Check comparison retrieval independently of the mocked full pipeline.
    calls=[]
    def per_doc(q,docs,k):
        calls.append((docs,k))
        return {'expanded_query':q,'retrieved':[{'chunk':{'doc_id':docs[0]}}], 'candidates':1,'reranked':False,'warnings':[]}
    original=chats.retrieve;chats.retrieve=per_doc
    try:
        result=ORIGINAL_GET_RETRIEVAL('Compare', ['d','d2'],6,True)
        assert calls==[(['d'],3),(['d2'],3)] and {x['chunk']['doc_id'] for x in result['retrieved']}=={'d','d2'}
    finally: chats.retrieve=original
    assert chats.compare_mode('auto','Compare methodologies',['d','d2'])
    assert not chats.compare_mode('auto','Compare methodologies',['d'])

@pytest.mark.asyncio
async def test_ollama_retry_backoff_and_explicit_num_ctx(monkeypatch):
    from app.core.generation import ollama_provider
    original=httpx.AsyncClient;calls=[];waits=[]
    def handler(request):
        if request.url.path=='/api/tags': return httpx.Response(200,json={'models':[{'name':'fake:latest'}]})
        calls.append(json.loads(request.content))
        if len(calls)<=3:return httpx.Response(503)
        return httpx.Response(200,content=b'{"message":{"content":"Answer [1]."},"done":false}\n{"done":true}\n')
    transport=httpx.MockTransport(handler)
    monkeypatch.setattr(ollama_provider.httpx,'AsyncClient',lambda **kw:original(transport=transport,**kw))
    async def sleep(seconds): waits.append(seconds)
    monkeypatch.setattr(ollama_provider.asyncio,'sleep',sleep)
    parts=[p async for p in OllamaProvider().stream([{'role':'user','content':'x'}],model='fake',temperature=.1,num_ctx=8192,max_tokens=1024)]
    assert parts==['Answer [1].'] and waits==[1.5,3,6]
    assert calls[-1]['options']=={'num_ctx':8192,'temperature':.1,'num_predict':1024}

def test_not_ready_rejected_and_out_of_range_citation_flagged(client):
    with connect() as db: db.execute("UPDATE documents SET status='indexing' WHERE id='d'")
    cid=new_chat(client)
    r=client.post(f'/api/v1/chats/{cid}/messages',json={'question':'What is the result?'})
    assert r.status_code==409 and r.json()['error']['code']=='DOCUMENT_NOT_READY'
    with connect() as db: db.execute("UPDATE documents SET status='ready' WHERE id='d'")
    app.state.llm_provider=Fake(['A supported answer [1], plus an invalid marker [9].'])
    ev=events(client.post(f'/api/v1/chats/{cid}/messages',json={'question':'What is the result?'}))
    mid=ev[0][1]['message_id']
    debug=client.get(f'/api/v1/chats/{cid}/messages/{mid}/debug').json()
    assert any('invalid_citation_markers' in warning for warning in debug['warnings'])

def test_no_chunks_refusal_skips_provider(client,monkeypatch):
    def empty(*args): return {'expanded_query':'q','retrieved':[],'candidates':0,'reranked':False,'warnings':[]}
    monkeypatch.setattr(chats,'get_retrieval',empty)
    class Never:
        async def stream(self,*args,**kwargs):
            raise AssertionError('Provider should not be called')
            yield ''
    app.state.llm_provider=Never();cid=new_chat(client)
    ev=events(client.post(f'/api/v1/chats/{cid}/messages',json={'question':'Question?'}))
    assert ev[-1][0]=='done' and ev[-1][1]['refused']
    assert next(x['text'] for name,x in ev if name=='token')=='I could not find this in the selected documents.'

def test_faithfulness_event_and_get_message_field(client,monkeypatch):
    monkeypatch.setattr('app.core.checks.faithfulness.nli_probabilities',lambda pairs:[.9 for _ in pairs])
    app.state.llm_provider=Fake(['The accuracy was 95 percent [1].'])
    cid=new_chat(client);ev=events(client.post(f'/api/v1/chats/{cid}/messages',json={'question':'What is the accuracy?'}))
    event=next(x for name,x in ev if name=='faithfulness')
    message=client.get(f"/api/v1/chats/{cid}/messages/{event['message_id']}").json()
    assert event['sentences']==message['faithfulness'] and event['sentences'][0]['label']=='supported'
    s=event['sentences'][0];assert message['content'][s['start']:s['end']]=='The accuracy was 95 percent [1].'
