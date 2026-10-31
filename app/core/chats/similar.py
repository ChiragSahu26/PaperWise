"""Local chat and question embeddings and similarity calculations."""
from collections import Counter
import math, re
import numpy as np
from app.db.session import connect
from app.core.retrieval.embed import embed
from app.core.retrieval.vector_store import collection, _lock, _clients
from app.core.retrieval.bm25 import tokenize, STOPWORDS
from app.api.settings import current_settings
import config

def chats_collection():
    collection()  # initialize persistent client
    key=str((config.DATA_DIR/'chroma').resolve())
    with _lock: return _clients[key].get_or_create_collection(name='chats',metadata={'hnsw:space':'cosine'})

def questions_collection():
    collection()
    key=str((config.DATA_DIR/'chroma').resolve())
    with _lock: return _clients[key].get_or_create_collection(name='questions',metadata={'hnsw:space':'cosine'})

def index_question(chat_id,message_id,text):
    vector=embed([text])[0]
    with connect() as db:
        if not db.execute("SELECT 1 FROM messages WHERE id=? AND chat_id=? AND role='user'",(message_id,chat_id)).fetchone(): return
    with _lock: questions_collection().upsert(ids=[message_id],embeddings=[vector],documents=[text],metadatas=[{'chat_id':chat_id,'message_id':message_id}])

def update_chat_vector(chat_id):
    with connect() as db:
        row=db.execute('SELECT title,summary,updated_at FROM chats WHERE id=?',(chat_id,)).fetchone()
        questions=[r[0] for r in db.execute("SELECT content FROM messages WHERE chat_id=? AND role='user' ORDER BY created_at",(chat_id,))]
    if not row or not questions: return
    title_summary=((row['title'] or '')+' '+(row['summary'] or '')).strip()
    vectors=np.asarray(embed(questions+[title_summary or questions[0]]),dtype=float)
    vector=.7*vectors[:-1].mean(axis=0)+.3*vectors[-1]
    norm=np.linalg.norm(vector)
    if norm: vector=vector/norm
    with connect() as db:
        if not db.execute('SELECT 1 FROM chats WHERE id=?',(chat_id,)).fetchone(): return
    with _lock: chats_collection().upsert(ids=[chat_id],embeddings=[vector.tolist()],metadatas=[{'updated_at':row['updated_at']}])

def delete_chat_vectors(chat_id):
    with _lock:
        col=chats_collection()
        if col.get(ids=[chat_id],include=[])['ids']: col.delete(ids=[chat_id])
        col=questions_collection(); ids=col.get(where={'chat_id':chat_id},include=[])['ids']
        if ids: col.delete(ids=ids)

def document_set(db,chat_id):
    # Use currently existing cited documents, falling back to active documents.
    cited={r[0] for r in db.execute('''SELECT DISTINCT c.doc_id FROM message_citations mc JOIN chunks c ON c.id=mc.chunk_id
        JOIN messages m ON m.id=mc.message_id WHERE m.chat_id=? AND mc.cited=1''',(chat_id,))}
    return cited or {r[0] for r in db.execute('SELECT doc_id FROM chat_documents WHERE chat_id=?',(chat_id,))}

def shared_words(db,a,b):
    docs={}
    for row in db.execute("SELECT chat_id,content FROM messages WHERE role='user'"):
        docs.setdefault(row['chat_id'],[]).extend(w for w in tokenize(row['content']) if w not in STOPWORDS and len(w)>2)
    left=Counter(docs.get(a,[]));right=Counter(docs.get(b,[])); n=max(len(docs),1)
    scores=[]
    for word in set(left)&set(right):
        df=sum(word in words for words in docs.values());idf=math.log((n+1)/(df+1))+1
        scores.append((min(left[word],right[word])*idf,word))
    return [word for _,word in sorted(scores,key=lambda x:(-x[0],x[1]))[:5]]

def similar_chats(chat_id,limit=5):
    with connect() as db:
        if not db.execute('SELECT 1 FROM chats WHERE id=?',(chat_id,)).fetchone():
            from app.errors import PaperWiseError
            raise PaperWiseError('NOT_FOUND','Chat not found.',404)
        with _lock:
            col=chats_collection(); source=col.get(ids=[chat_id],include=['embeddings'])
            if not source['ids'] or col.count()<2: return []
            result=col.query(query_embeddings=[source['embeddings'][0]],n_results=col.count(),include=['distances'])
        doc_a=document_set(db,chat_id); weights=current_settings()['similarity_weights']; output=[]
        dismissed={r[0] for r in db.execute('SELECT other_chat_id FROM similar_dismissals WHERE chat_id=? UNION SELECT chat_id FROM similar_dismissals WHERE other_chat_id=?',(chat_id,chat_id))}
        for other,distance in zip(result['ids'][0],result['distances'][0]):
            if other==chat_id or other in dismissed: continue
            row=db.execute('SELECT title FROM chats WHERE id=?',(other,)).fetchone()
            if not row: continue
            doc_b=document_set(db,other); union=doc_a|doc_b
            overlap=len(doc_a&doc_b)/len(union) if union else 0
            sim=weights['topic']*(1-float(distance))+weights['docs']*overlap
            if sim<config.SIM_THRESHOLD: continue
            shared=doc_a&doc_b
            titles=[r[0] for r in db.execute('SELECT COALESCE(title,filename) FROM documents WHERE id IN ('+','.join('?' for _ in shared)+')',tuple(shared))] if shared else []
            output.append({'chat_id':other,'title':row['title'],'similarity':sim,'reasons':{'shared_topics':shared_words(db,chat_id,other),'shared_docs':titles}})
    return sorted(output,key=lambda x:(-x['similarity'],x['chat_id']))[:limit]

def duplicate(question):
    vector=embed([question])[0]
    with _lock:
        col=questions_collection()
        if col.count()==0: return None
        result=col.query(query_embeddings=[vector],n_results=min(10,col.count()),include=['distances','documents','metadatas'])
    with connect() as db:
        for mid,dist,txt,meta in zip(result['ids'][0],result['distances'][0],result['documents'][0],result['metadatas'][0]):
            similarity=1-float(dist)
            if similarity<config.DUPLICATE_THRESHOLD: return None
            if db.execute("SELECT 1 FROM messages WHERE id=? AND chat_id=? AND role='user'",(mid,meta['chat_id'])).fetchone():
                return {'chat_id':meta['chat_id'],'message_id':mid,'question':txt,'similarity':similarity}
    return None
