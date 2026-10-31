"""Opt-in notes vector index. Only notes anchored to active documents are searched."""
import json,threading
import config
from app.db.session import connect
from app.api.settings import current_settings
from app.core.retrieval.embed import embed
from app.core.retrieval.vector_store import collection,_clients,_lock
note_lock=threading.RLock()

def notes_collection():
    collection();key=str((config.DATA_DIR/'chroma').resolve())
    with _lock:return _clients[key].get_or_create_collection(name='notes',metadata={'hnsw:space':'cosine'})

def remove_index(note_id):
    with note_lock:
        nid='note:'+note_id
        with _lock:
            col=notes_collection()
            if col.get(ids=[nid],include=[])['ids']:col.delete(ids=[nid])
        with connect() as db:db.execute('DELETE FROM chunks WHERE id=? AND type=?',(nid,'note'))

def index_note(note_id):
    with note_lock:
        if not current_settings()['notes_in_retrieval']:return
        with connect() as db:row=db.execute('SELECT * FROM notes WHERE id=?',(note_id,)).fetchone()
        if not row or not row['doc_id']:
            remove_index(note_id);return
        vector=embed([row['body_md']])[0]; anchor=json.loads(row['anchor_json']) if row['anchor_json'] else {}
        nid='note:'+note_id; page=anchor.get('page');boxes=anchor.get('bboxes')
        with connect() as db:
            db.execute('''INSERT INTO chunks(id,doc_id,segment_index,chunk_index,type,text,location_label,page,char_start,char_end,bboxes_json)
             VALUES (?,?,NULL,NULL,'note',?,'Your note',?,0,?,?) ON CONFLICT(id) DO UPDATE SET doc_id=excluded.doc_id,text=excluded.text,page=excluded.page,char_end=excluded.char_end,bboxes_json=excluded.bboxes_json''',
             (nid,row['doc_id'],row['body_md'],page,len(row['body_md']),json.dumps(boxes) if boxes else None))
        with _lock:notes_collection().upsert(ids=[nid],embeddings=[vector],documents=[row['body_md']],metadatas=[{'doc_id':row['doc_id'],'note_id':note_id}])

def reindex():
    with connect() as db:ids=[r[0] for r in db.execute('SELECT id FROM notes')]
    for note_id in ids:index_note(note_id)

def search_notes(doc_ids,vector,limit):
    if not doc_ids:return []
    with _lock:
        col=notes_collection()
        if not col.count():return []
        r=col.query(query_embeddings=[vector],where={'doc_id':{'$in':doc_ids}},n_results=min(limit,col.count()),include=['distances'])
    return [(i,1-float(d)) for i,d in zip(r['ids'][0],r['distances'][0])]

def note_vectors_for(ids):
    if not ids:return {}
    with _lock:result=notes_collection().get(ids=ids,include=['embeddings'])
    return {cid:v for cid,v in zip(result['ids'],result['embeddings'])}
