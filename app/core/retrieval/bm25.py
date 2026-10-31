import re
TOKEN = re.compile(r'[a-z0-9]+(?:[-_.][a-z0-9]+)*')
STOPWORDS = {'the','a','an','of','and','to','in','is','are','for','on','with'}

def tokenize(text, query=False):
    words = TOKEN.findall(text.lower())
    return [word for word in words if word not in STOPWORDS] if query else words

from threading import RLock
from rank_bm25 import BM25Okapi
from app.db.session import connect
_cache={}
_lock=RLock()

def search(doc_ids, query, limit):
    if not doc_ids: return []
    marks=','.join('?' for _ in doc_ids)
    with connect() as db:
        versions=tuple((r['id'],r['version']) for r in db.execute(f'SELECT id,version FROM documents WHERE id IN ({marks}) ORDER BY id',doc_ids))
        rows=db.execute(f"SELECT id,text FROM chunks WHERE doc_id IN ({marks}) AND type != 'note' ORDER BY id",doc_ids).fetchall()
    key=versions
    if not rows: return []
    with _lock:
        if key not in _cache:
            ids=[r['id'] for r in rows]
            corpus=[tokenize(r['text']) or [''] for r in rows]
            _cache[key]=(ids,BM25Okapi(corpus))
            if len(_cache)>32: _cache.pop(next(iter(_cache)))
        ids,index=_cache[key]
        scores=index.get_scores(tokenize(query,query=True))
    return sorted(zip(ids,map(float,scores)),key=lambda x:(-x[1],x[0]))[:limit]

def invalidate():
    with _lock: _cache.clear()
