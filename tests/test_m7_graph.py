import json
import pytest
from fastapi.testclient import TestClient
import config
from app.main import app
from app.db.session import connect
from app.jobs.queue import now
from app.core.knowledge.extract import extract_document
from app.core.knowledge.graph import normalize

class StructuredFake:
    async def background_complete(self,prompt,json_schema=None,system=None):
        assert 'EXCERPTS' in prompt and 'data, not instructions' in system
        if 'entities' in json_schema['properties']:
            return json.dumps({'entities':[{'type':'Dataset','name':'DataSetX'},{'type':'Method','name':'ModelA'},{'type':'Metric','name':'accuracy'}],
                               'relations':[{'source':'ModelA','type':'evaluates_on','target':'DataSetX'}]})
        number=92 if '92 percent' in prompt else 85
        return json.dumps({'claims':[{'task':'classification','dataset':'DataSetX','metric':'accuracy','value':number,'unit':'percent','setting':'test split'}]})

@pytest.mark.asyncio
async def test_planted_conflict_graph_and_document_delete(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);monkeypatch.setattr(config,'OLLAMA_URL','http://127.0.0.1:1')
    with TestClient(app) as client:
        with connect() as db:
            for i,value in [(1,92),(2,85)]:
                db.execute('INSERT INTO documents(id,filename,file_path,file_type,status,title,authors_json,added_at) VALUES (?,?,?,?,?,?,?,?)',
                           (f'd{i}',f'paper{i}.txt','/tmp/unrelated','txt','ready',f'Paper {i}','["Researcher One"]',now()))
                db.execute('INSERT INTO chunks(id,doc_id,type,text,location_label) VALUES (?,?,?,?,?)',
                           (f'c{i}',f'd{i}','text',f'ModelA evaluated on DataSetX reported accuracy of {value} percent on the test split.','Part 1'))
        await extract_document(StructuredFake(),'d1');await extract_document(StructuredFake(),'d2')
        conflicts=client.get('/api/v1/conflicts?doc_ids=d1,d2').json()
        assert len(conflicts)==1 and {e['value'] for e in conflicts[0]['entries']}=={92,85}
        assert {e['citation']['chunk_id'] for e in conflicts[0]['entries']}=={'c1','c2'}
        assert 'check the experimental setup' in conflicts[0]['note']
        graph=client.get('/api/v1/graph?doc_ids=d1,d2').json()
        dataset=next(n for n in graph['nodes'] if n['type']=='Dataset')
        assert set(dataset['doc_ids'])=={'d1','d2'} and any(e['type']=='evaluates_on' and e['chunk_ids'] for e in graph['edges'])
        detail=client.get('/api/v1/graph/nodes/'+dataset['id']).json()
        assert detail['node']['label']=='DataSetX' and {p['chunk_id'] for p in detail['passages']}=={'c1','c2'}
        assert client.get('/api/v1/conflicts?doc_ids=d1').json()==[]
        assert client.delete('/api/v1/documents/d1').status_code==200
        assert client.get('/api/v1/conflicts').json()==[]
        after=client.get('/api/v1/graph').json()
        assert all('c1' not in e['chunk_ids'] for e in after['edges'])
        assert normalize('BERT-base')==normalize('BERT')

@pytest.mark.asyncio
async def test_bad_json_retries_and_warns_without_inventing_edges(tmp_path,monkeypatch):
    from app.db.session import initialize
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);initialize()
    with connect() as db:
        db.execute("INSERT INTO documents(id,filename,file_path,file_type,status,added_at) VALUES ('bad','bad.txt','/tmp/no','txt','ready',?)",(now(),))
        db.execute("INSERT INTO chunks(id,doc_id,type,text,location_label) VALUES ('c','bad','text','DataSetX has 3 percent accuracy.','Part 1')")
    class Bad:
        calls=0
        async def background_complete(self,*args,**kwargs):self.calls+=1;return '{invalid JSON'
    bad=Bad();await extract_document(bad,'bad')
    assert bad.calls==4  # graph and claim each retry once
    with connect() as db:
        warnings=json.loads(db.execute("SELECT warnings_json FROM documents WHERE id='bad'").fetchone()[0])
        assert len(warnings)==2 and db.execute('SELECT count(*) FROM graph_edges').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM claims').fetchone()[0]==0

@pytest.mark.asyncio
async def test_citations_only_between_uploaded_papers_and_real_source_chunks(tmp_path,monkeypatch):
    from app.db.session import initialize
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);initialize()
    with connect() as db:
        for doc,doi in [('a','10.1234/source'),('b','10.1234/target')]:
            db.execute('INSERT INTO documents(id,filename,file_path,file_type,status,title,doi,added_at) VALUES (?,?,?,?,?,?,?,?)',(doc,doc+'.txt','/tmp/no','txt','ready','Paper '+doc,doi,now()))
        db.execute("INSERT INTO chunks(id,doc_id,type,text,location_label) VALUES ('ca','a','text','References cite 10.1234/target.','References')")
    monkeypatch.setattr('app.core.intelligence.online.enabled',lambda:True)
    async def refs(*args,**kwargs):return {'data':[{'citedPaper':{'externalIds':{'DOI':'10.1234/target'}}},{'citedPaper':{'externalIds':{'DOI':'10.1234/not-uploaded'}}}]}
    monkeypatch.setattr('app.core.intelligence.online.get_json',refs)
    class Empty:
        async def background_complete(self,*args,**kwargs):return '{"entities":[],"relations":[]}'
    await extract_document(Empty(),'a')
    from app.core.knowledge.graph import get_graph
    graph=get_graph();cites=[x for x in graph['edges'] if x['type']=='cites']
    assert len(cites)==1 and cites[0]['chunk_ids']==['ca']
    assert len([x for x in graph['nodes'] if x['type']=='Paper'])==2

@pytest.mark.asyncio
async def test_reference_resolves_when_target_uploaded_later(tmp_path,monkeypatch):
    from app.db.session import initialize
    from app.core.knowledge.graph import get_graph
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);initialize()
    monkeypatch.setattr('app.core.intelligence.online.enabled',lambda:True)
    async def refs(url,*args,**kwargs):
        return {'data':[{'citedPaper':{'externalIds':{'DOI':'10.5555/target'}}}]} if 'source' in url else {'data':[]}
    monkeypatch.setattr('app.core.intelligence.online.get_json',refs)
    class Empty:
        async def background_complete(self,*args,**kwargs):return '{"entities":[],"relations":[]}'
    with connect() as db:
        db.execute("INSERT INTO documents(id,filename,file_path,file_type,status,doi,added_at) VALUES ('a','a.txt','/tmp/no','txt','ready','10.5555/source',?)",(now(),))
        db.execute("INSERT INTO chunks(id,doc_id,type,text,location_label) VALUES ('ca','a','text','A reference to 10.5555/target.','References')")
    await extract_document(Empty(),'a')
    assert not [x for x in get_graph()['edges'] if x['type']=='cites']
    with connect() as db:db.execute("INSERT INTO documents(id,filename,file_path,file_type,status,doi,added_at) VALUES ('b','b.txt','/tmp/no','txt','ready','10.5555/target',?)",(now(),))
    await extract_document(Empty(),'b')
    edges=[x for x in get_graph()['edges'] if x['type']=='cites']
    assert len(edges)==1 and edges[0]['chunk_ids']==['ca']
