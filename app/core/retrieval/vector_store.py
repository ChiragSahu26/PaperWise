"""Chroma vectors only. SQLite owns chunk contents and metadata."""
import threading
import chromadb
import config
from app.core.retrieval.embed import embed
_clients={}
_lock=threading.RLock()

def collection():
    path=str((config.DATA_DIR/'chroma').resolve())
    with _lock:
        if path not in _clients:
            _clients[path]=chromadb.PersistentClient(path=path)
        return _clients[path].get_or_create_collection(name='chunks',metadata={'hnsw:space':'cosine'})

def replace_document(doc_id,chunks):
    # Embedding first ensures a model failure cannot destroy an existing index.
    vectors=embed([c.text for c in chunks])
    with _lock:
        col=collection()
        old=set(col.get(where={'doc_id':doc_id},include=[])['ids'])
        for offset in range(0,len(chunks),64):
            group=chunks[offset:offset+64]; embeddings=vectors[offset:offset+64]
            meta=[]
            for c in group:
                entry={'doc_id':doc_id,'chunk_id':c.id,'type':c.type,'location_label':c.location_label}
                if c.page is not None: entry['page']=c.page
                meta.append(entry)
            col.upsert(ids=[c.id for c in group],embeddings=embeddings,documents=[c.text for c in group],metadatas=meta)
        stale=old-{c.id for c in chunks}
        if stale: col.delete(ids=list(stale))

def delete_document(doc_id):
    with _lock:
        col=collection()
        ids=col.get(where={'doc_id':doc_id},include=[])['ids']
        if ids: col.delete(ids=ids)

def semantic_search(doc_ids, vector, limit):
    if not doc_ids or limit < 1: return []
    with _lock:
        col=collection()
        if col.count()==0: return []
        result=col.query(query_embeddings=[vector],n_results=min(limit,col.count()),where={'doc_id':{'$in':doc_ids}},include=['distances'])
    return [(cid,1-float(distance)) for cid,distance in zip(result['ids'][0],result['distances'][0])]

def vectors_for(ids):
    if not ids: return {}
    with _lock: result=collection().get(ids=ids,include=['embeddings'])
    return {cid:vector for cid,vector in zip(result['ids'],result['embeddings'])}

def staging_collection(name):
    collection()
    return _clients[str((config.DATA_DIR/'chroma').resolve())].get_or_create_collection(name=name,metadata={'hnsw:space':'cosine'})

def stage_vectors(job_id,chunks):
    vectors=embed([c.text for c in chunks])
    col=staging_collection('ingest_staging')
    for i in range(0,len(chunks),64):
        group=chunks[i:i+64];metas=[]
        for c in group:
            m={'job_id':job_id,'doc_id':c.doc_id,'chunk_id':c.id,'type':c.type,'location_label':c.location_label}
            if c.page is not None:m['page']=c.page
            metas.append(m)
        col.upsert(ids=[job_id+'|'+c.id for c in group],embeddings=vectors[i:i+64],documents=[c.text for c in group],metadatas=metas)

def backup_vectors(doc_id,job_id):
    main=collection();backup=staging_collection('ingest_backup');offset=0
    while True:
        data=main.get(where={'doc_id':doc_id},limit=64,offset=offset,include=['embeddings','documents','metadatas'])
        if not data['ids']:break
        backup.upsert(ids=[job_id+'|'+i for i in data['ids']],embeddings=data['embeddings'],documents=data['documents'],metadatas=[{**m,'job_id':job_id} for m in data['metadatas']])
        offset+=len(data['ids'])

def apply_staged_vectors(doc_id,job_id,db):
    main=collection();stage=staging_collection('ingest_staging');offset=0
    while True:
        data=stage.get(where={'job_id':job_id},limit=64,offset=offset,include=['embeddings','documents','metadatas'])
        if not data['ids']:break
        main.upsert(ids=[m['chunk_id'] for m in data['metadatas']],embeddings=data['embeddings'],documents=data['documents'],metadatas=[{k:v for k,v in m.items() if k!='job_id'} for m in data['metadatas']])
        offset+=len(data['ids'])
    cursor=db.execute('SELECT id FROM chunks WHERE doc_id=? AND NOT EXISTS (SELECT 1 FROM ingest_stage_chunks s WHERE s.job_id=? AND s.id=chunks.id)',(doc_id,job_id))
    while old:=cursor.fetchmany(64):main.delete(ids=[r['id'] for r in old])

def restore_backup(doc_id,job_id):
    main=collection();backup=staging_collection('ingest_backup')
    while True:
        ids=main.get(where={'doc_id':doc_id},limit=64,include=[])['ids']
        if not ids:break
        main.delete(ids=ids)
    offset=0
    while True:
        data=backup.get(where={'job_id':job_id},limit=64,offset=offset,include=['embeddings','documents','metadatas'])
        if not data['ids']:break
        main.upsert(ids=[m['chunk_id'] for m in data['metadatas']],embeddings=data['embeddings'],documents=data['documents'],metadatas=[{k:v for k,v in m.items() if k!='job_id'} for m in data['metadatas']])
        offset+=len(data['ids'])

def cleanup_stage(job_id):
    for name in ('ingest_staging','ingest_backup'):
        col=staging_collection(name)
        # Chroma supports delete by where without loading IDs into Python.
        col.delete(where={'job_id':job_id})

def recover_interrupted_ingests():
    from app.db.session import connect
    with _lock:
        with connect() as db:rows=db.execute('SELECT doc_id,job_id FROM ingest_recovery').fetchall()
        for row in rows:
            restore_backup(row['doc_id'],row['job_id'])
            with connect() as db:db.execute('DELETE FROM ingest_recovery WHERE doc_id=?',(row['doc_id'],))
        # Staged copies never become queryable and are disposable after recovery.
        for name in ('ingest_staging','ingest_backup'):
            col=staging_collection(name)
            while ids:=col.get(limit=1000,include=[])['ids']:col.delete(ids=ids)
        with connect() as db:db.execute('DELETE FROM ingest_stage_chunks')
