import uuid
import numpy as np
from sklearn.cluster import AgglomerativeClustering
from app.core.chats.similar import chats_collection
from app.core.retrieval.vector_store import _lock
from app.db.session import connect
from app.jobs.queue import now
import config

def clusters():
    with _lock: data=chats_collection().get(include=['embeddings'])
    if len(data['ids'])<2: return []
    ids=data['ids']; vectors=np.asarray(data['embeddings'])
    labels=AgglomerativeClustering(n_clusters=None,metric='cosine',linkage='average',distance_threshold=1-config.SIM_THRESHOLD).fit_predict(vectors)
    groups={}
    for cid,label in zip(ids,labels): groups.setdefault(int(label),[]).append(cid)
    with connect() as db:
        result=[]
        for ids in groups.values():
            if len(ids)<2: continue
            records=[db.execute('SELECT id,title FROM chats WHERE id=?',(cid,)).fetchone() for cid in ids]
            records=[r for r in records if r is not None]
            if len(records)>1: result.append([(r['id'],r['title'] or 'Untitled chat') for r in records])
    return result

def save_groups(groups):
    with connect() as db:
        db.execute('UPDATE chats SET topic_id=NULL');db.execute('DELETE FROM topics')
        for members,label in groups:
            tid=str(uuid.uuid4());db.execute('INSERT INTO topics(id,label,updated_at) VALUES (?,?,?)',(tid,label,now()))
            db.executemany('UPDATE chats SET topic_id=? WHERE id=?',[(tid,cid) for cid,_ in members])

def list_topics():
    with connect() as db:
        result=[]
        for t in db.execute('SELECT * FROM topics ORDER BY label').fetchall():
            chats=[r[0] for r in db.execute('SELECT id FROM chats WHERE topic_id=? ORDER BY id',(t['id'],))]
            if len(chats)<2: continue
            placeholders=','.join('?' for _ in chats)
            docs=[r[0] for r in db.execute(f'SELECT DISTINCT doc_id FROM chat_documents WHERE chat_id IN ({placeholders}) ORDER BY doc_id',chats)]
            result.append({'topic_id':t['id'],'label':t['label'],'chat_ids':chats,'doc_ids':docs})
        return result
