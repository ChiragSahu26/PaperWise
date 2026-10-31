import threading
import pytest
import fitz
import config
from app.db.session import initialize,connect
from app.jobs.ingest import ingest_document,IngestionCancelled
from app.jobs.queue import now
from app.core.retrieval import vector_store as vs

def seed(doc,path,job):
    with connect() as db:
        db.execute('INSERT INTO documents(id,filename,file_path,file_type,status,added_at) VALUES (?,?,?,?,?,?)',(doc,path.name,str(path),path.suffix[1:],'queued',now()))
        db.execute("INSERT INTO jobs(id,kind,status,created_at,updated_at) VALUES (?,'ingest','running',?,?)",(job,now(),now()))

def test_501_page_pdf_batched_progress(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);monkeypatch.setattr(config,'OCR_MIN_CHARS_PER_PAGE',0)
    batches=[]
    def embed(texts):
        batches.append(len(texts));return [[1.,0.] for _ in texts]
    monkeypatch.setattr(vs,'embed',embed);initialize()
    pdf=fitz.open()
    for i in range(501):
        p=pdf.new_page();p.insert_text((80,100),f'Page {i+1} presents a useful experiment result with reliable observations.')
    path=tmp_path/'large.pdf';pdf.save(str(path));pdf.close();seed('large',path,'job')
    events=[];ingest_document('large','job',events.append)
    with connect() as db:
        doc=db.execute("SELECT status,page_count FROM documents WHERE id='large'").fetchone()
        ids={r[0] for r in db.execute("SELECT id FROM chunks WHERE doc_id='large'")}
        assert doc['status']=='ready' and doc['page_count']==501 and len(ids)==502
        assert db.execute('SELECT count(*) FROM ingest_stage_chunks').fetchone()[0]==0
    assert ids==set(vs.collection().get(where={'doc_id':'large'},include=[])['ids'])
    assert max(batches)<=64 and len(batches)>=8
    assert any('Processed 496 of 501' in e['message'] for e in events)
    assert events[-1]['status']=='ready'

def test_failed_commit_and_crash_recovery_restore_old_vectors(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);monkeypatch.setattr(vs,'embed',lambda texts:[[1.,0.] if 'old' in t else [0.,1.] for t in texts]);initialize()
    path=tmp_path/'paper.txt';path.write_text('The old source text has a specific research result.')
    seed('d',path,'j1');ingest_document('d','j1',lambda e:None)
    before=vs.collection().get(where={'doc_id':'d'},include=['embeddings','documents']);oldids=set(before['ids']);oldtexts=before['documents']
    path.write_text('The new source text has a revised research result.')
    with connect() as db:db.execute("INSERT INTO jobs(id,kind,status,created_at,updated_at) VALUES ('j2','ingest','running',?,?)",(now(),now()))
    original=vs.apply_staged_vectors
    def fail(doc,job,db):original(doc,job,db);raise RuntimeError('injected failure after writing vectors')
    monkeypatch.setattr(vs,'apply_staged_vectors',fail)
    with pytest.raises(RuntimeError):ingest_document('d','j2',lambda e:None)
    after=vs.collection().get(where={'doc_id':'d'},include=['documents'])
    assert set(after['ids'])==oldids and after['documents']==oldtexts
    with connect() as db:
        assert {r[0] for r in db.execute("SELECT id FROM chunks WHERE doc_id='d'")}==oldids
        assert db.execute('SELECT count(*) FROM ingest_recovery').fetchone()[0]==0
    # Emulate a hard process interruption after the journal is durable.
    with vs._lock:
        vs.backup_vectors('d','crash')
        with connect() as db:db.execute("INSERT INTO ingest_recovery VALUES ('d','crash')")
        vs.collection().delete(where={'doc_id':'d'})
    vs.recover_interrupted_ingests()
    recovered=vs.collection().get(where={'doc_id':'d'},include=['documents'])
    assert set(recovered['ids'])==oldids and recovered['documents']==oldtexts

def test_cancellation_before_commit_preserves_sqlite_and_vectors(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);monkeypatch.setattr(vs,'embed',lambda texts:[[1.,0.] for _ in texts]);initialize()
    path=tmp_path/'paper.txt';path.write_text('Old research evidence is stored safely here.')
    seed('d',path,'j1');ingest_document('d','j1',lambda e:None)
    before=vs.collection().get(where={'doc_id':'d'},include=['documents'])
    path.write_text('Changed research evidence should not be committed.')
    with connect() as db:db.execute("INSERT INTO jobs(id,kind,status,created_at,updated_at) VALUES ('j2','ingest','running',?,?)",(now(),now()))
    cancel=threading.Event();original=vs.stage_vectors
    def stop(job,chunks):original(job,chunks);cancel.set()
    monkeypatch.setattr(vs,'stage_vectors',stop)
    with pytest.raises(IngestionCancelled):ingest_document('d','j2',lambda e:None,cancel)
    after=vs.collection().get(where={'doc_id':'d'},include=['documents'])
    assert after['ids']==before['ids'] and after['documents']==before['documents']
    with connect() as db:assert db.execute('SELECT count(*) FROM ingest_stage_chunks').fetchone()[0]==0

def test_queue_shutdown_cancels_and_awaits_ingest_thread(tmp_path,monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr(config,'DATA_DIR',tmp_path);monkeypatch.setattr(config,'OLLAMA_URL','http://127.0.0.1:1')
    monkeypatch.setattr(vs,'embed',lambda texts:[[1.,0.] for _ in texts])
    reached=threading.Event();release=threading.Event();finished=threading.Event();original=vs.stage_vectors
    def pause(job,chunks):
        reached.set();release.wait(5);original(job,chunks);finished.set()
    monkeypatch.setattr(vs,'stage_vectors',pause)
    with TestClient(app) as client:
        doc=client.post('/api/v1/documents',files={'files':('paper.txt',b'A sufficiently long research result about models and data.','text/plain')}).json()[0]['doc_id']
        assert reached.wait(5)
        threading.Timer(.1,release.set).start()
    assert finished.is_set()  # close awaited the thread; it cannot write later
    with connect() as db:
        job=db.execute("SELECT status,error FROM jobs WHERE kind='ingest'").fetchone()
        record=db.execute('SELECT status,error FROM documents WHERE id=?',(doc,)).fetchone()
        assert (job['status'],job['error'])==('failed','interrupted')
        assert (record['status'],record['error'])==('failed','interrupted')
        assert db.execute('SELECT count(*) FROM chunks').fetchone()[0]==0
    assert not vs.collection().get(where={'doc_id':doc},include=[])['ids']
