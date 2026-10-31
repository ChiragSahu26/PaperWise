import json, logging, re
import numpy as np
import config
from app.db.session import connect
from app.errors import PaperWiseError
from app.api.settings import current_settings
from .expand import expand_query
from .embed import embed
from .bm25 import search as bm25_search
from .hybrid import merge_scores
from .vector_store import semantic_search, vectors_for
from .confidence import evidence_match
from .rerank import score as rerank

log=logging.getLogger(__name__)
METADATA_QUERY=re.compile(r'\b(title|authors?|who wrote|written by|affiliation|abstract|what is this paper|about this paper|summary of the paper)\b',re.I)

def validate_documents(doc_ids):
    if not doc_ids: raise PaperWiseError('NO_DOCUMENTS_SELECTED','No documents selected.',400)
    marks=','.join('?' for _ in doc_ids)
    with connect() as db: rows=db.execute(f'SELECT id,status FROM documents WHERE id IN ({marks})',doc_ids).fetchall()
    state={r['id']:r['status'] for r in rows}
    if any(d not in state for d in doc_ids): raise PaperWiseError('NOT_FOUND','Document not found.',404)
    if any(state[d]!='ready' for d in doc_ids): raise PaperWiseError('DOCUMENT_NOT_READY','A selected document is not ready.',409)

def retrieve(question, doc_ids, top_k=None, mode='hybrid_rerank'):
    if mode not in {'semantic','bm25','hybrid','hybrid_rerank'}: raise ValueError('Invalid retrieval mode')
    doc_ids=sorted(set(doc_ids)); validate_documents(doc_ids)
    settings=current_settings(); top_k=top_k or settings['top_k']
    if not 1<=top_k<=20: raise PaperWiseError('VALIDATION_ERROR','top_k must be between 1 and 20.',422)
    expanded=expand_query(question)
    query_vectors=embed([expanded,question]); ev,qv=query_vectors
    sem=dict(semantic_search(doc_ids,ev,config.CANDIDATE_POOL)) if mode!='bm25' else {}
    if settings['notes_in_retrieval'] and mode!='bm25':
        from app.core.notes.index import search_notes
        sem.update(dict(search_notes(doc_ids,ev,config.CANDIDATE_POOL)))
        sem=dict(sorted(sem.items(),key=lambda x:(-x[1],x[0]))[:config.CANDIDATE_POOL])
    lex=dict(bm25_search(doc_ids,expanded,config.CANDIDATE_POOL)) if mode!='semantic' else {}
    if mode=='semantic': ranking=sorted(sem.items(),key=lambda x:(-x[1],x[0]))
    elif mode=='bm25': ranking=sorted(lex.items(),key=lambda x:(-x[1],x[0]))
    else: ranking=merge_scores(sem,lex,settings['hybrid_weights']['semantic'],settings['hybrid_weights']['bm25'])
    marks=','.join('?' for _ in doc_ids)
    with connect() as db:
        rows=db.execute(f'SELECT c.*, d.title, d.filename, d.file_type FROM chunks c JOIN documents d ON d.id=c.doc_id WHERE c.doc_id IN ({marks})',doc_ids).fetchall()
    # PDF excerpts without a traceable page and boxes cannot support viewer highlights.
    chunks={r['id']:dict(r) for r in rows if (r['type']!='note' or settings['notes_in_retrieval']) and (r['type']=='note' or r['file_type']!='pdf' or (r['page'] is not None and r['bboxes_json'] and json.loads(r['bboxes_json'])))}
    for c in chunks.values():
        if c['type']=='note':c['title']='Your note'
    ranking=[(i,s) for i,s in ranking if i in chunks]
    if METADATA_QUERY.search(question):
        metas=[i for i,c in chunks.items() if c['type']=='metadata']
        scores=dict(ranking)
        ranking=[(i,scores.get(i,0.0)) for i in metas]+[(i,s) for i,s in ranking if i not in metas]
    hybrid_scores=dict(ranking)
    used_reranker=False; warnings=[]; rerank_scores={}
    if mode=='hybrid_rerank' and settings['use_reranker'] and ranking:
        short=ranking[:config.RERANK_SHORTLIST]
        try:
            scores=rerank(question,[chunks[cid]['text'] for cid,_ in short])
            rerank_scores=dict(zip((i for i,_ in short),scores))
            ranking=sorted(short,key=lambda p:(-rerank_scores[p[0]],p[0]))
            used_reranker=True
        except Exception:
            log.warning('Cross-encoder unavailable; using hybrid ranking',exc_info=True)
            warnings.append('reranker_unavailable')
    selected=ranking[:top_k]
    if METADATA_QUERY.search(question) and selected and not any(chunks[i]['type']=='metadata' for i,_ in selected):
        metadata=next((i for i in hybrid_scores if chunks[i]['type']=='metadata'),None)
        if metadata: selected[-1]=(metadata,hybrid_scores[metadata])
    ids=[i for i,_ in selected]
    vec=vectors_for([i for i in ids if chunks[i]['type']!='note'])
    note_ids=[i for i in ids if chunks[i]['type']=='note']
    if note_ids:
        from app.core.notes.index import note_vectors_for
        vec.update(note_vectors_for(note_ids))
    items=[]
    for rank,(cid,_) in enumerate(selected,1):
        c=chunks[cid]
        cosine=float(np.dot(qv,vec[cid])) if cid in vec else 0.0
        c['bboxes']=json.loads(c['bboxes_json']) if c['bboxes_json'] else None
        items.append({'chunk':c,'hybrid_score':hybrid_scores[cid],'rerank_score':rerank_scores.get(cid),'cosine':cosine,'rank':rank})
    return {'expanded_query':expanded,'retrieved':items,'confidence':evidence_match([x['cosine'] for x in items]),
            'candidates':len(hybrid_scores),'reranked':used_reranker,'warnings':warnings}
