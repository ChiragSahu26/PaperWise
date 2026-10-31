import asyncio, json, logging, re, time, uuid
from typing import Literal
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from app.db.session import connect
from app.errors import PaperWiseError
from app.jobs.queue import now
from app.api.settings import current_settings
from app.core.retrieval.search import validate_documents, retrieve
from app.core.retrieval.confidence import evidence_match
from app.core.generation.prompts import assemble
from app.core.generation.refusal import RefusalBuffer, PREFIX, cited_markers
import config

log=logging.getLogger(__name__)
router=APIRouter()
class CreateChat(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title: str | None = None
    doc_ids: list[str] = Field(default_factory=list)
class PatchChat(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title: str | None = None
    pinned: bool | None = None
    doc_ids: list[str] | None = None
    model: str | None = None
class SendMessage(BaseModel):
    model_config=ConfigDict(extra='forbid')
    question: str = Field(min_length=1)
    doc_ids: list[str] | None = None
    top_k: int | None = Field(default=None,ge=1,le=20)
    mode: Literal['auto','qa','compare']='auto'
    model: str | None = None

class Confidence(BaseModel):
    level:Literal['low','medium','high']
    score:float
class FaithfulnessSentence(BaseModel):
    start:int
    end:int
    label:Literal['supported','partial','unsupported']
    chunk_ids:list[str]
class CitationResponse(BaseModel):
    marker:int
    chunk_id:str|None
    doc_id:str|None
    doc_title:str|None
    location_label:str|None
    page:int|None
    bboxes:list[list[float]]|None
    snippet:str|None
    highlight_span:dict|None
    score:float|None
    cited:bool
class MessageResponse(BaseModel):
    id:str
    role:str
    content:str
    created_at:str
    mode:str|None
    model:str|None
    refused:bool
    confidence:Confidence|None
    citations:list[CitationResponse]
    faithfulness:list[FaithfulnessSentence]|None
    tokens:int|None
    latency_ms:int|None

class Generation:
    def __init__(self,chat_id):
        self.chat_id=chat_id; self.stopped=False; self.pending=None
    def stop(self):
        self.stopped=True
        if self.pending and not self.pending.done(): self.pending.cancel()

def find_chat(db,chat_id):
    row=db.execute('SELECT * FROM chats WHERE id=?',(chat_id,)).fetchone()
    if row is None: raise PaperWiseError('NOT_FOUND','Chat not found.',404)
    return row

def render_chat(db,row,messages=False):
    data={'id':row['id'],'title':row['title'],'summary':row['summary'],'updated_at':row['updated_at'],
          'doc_ids':[r[0] for r in db.execute('SELECT doc_id FROM chat_documents WHERE chat_id=? ORDER BY doc_id',(row['id'],))],
          'pinned':bool(row['pinned']),'topic_id':row['topic_id'],'model':row['model']}
    if messages:
        data['messages']=[render_message(db,r) for r in db.execute('SELECT * FROM messages WHERE chat_id=? ORDER BY created_at,id',(row['id'],))]
    return data

def render_message(db,row):
    debug=json.loads(row['debug_json']) if row['debug_json'] else {}
    retrieved=debug.get('retrieved',[])
    citations=[]
    for c in db.execute('SELECT * FROM message_citations WHERE message_id=? ORDER BY marker',(row['id'],)):
        record=retrieved[c['marker']-1] if c['marker']<=len(retrieved) else {}
        page=c['page']; removed=c['chunk_id'] is None
        citations.append({'marker':c['marker'],'chunk_id':c['chunk_id'],'doc_id':record.get('doc_id'),
            'doc_title':c['doc_title'],'location_label':c['location_label'],'page':page,
            'bboxes':json.loads(c['bboxes_json']) if c['bboxes_json'] and not removed else None,
            'snippet':c['snippet'],'highlight_span':{'start':c['highlight_start'],'end':c['highlight_end']} if not removed and page is not None and c['highlight_start'] is not None else None,
            'score':c['score'],'cited':bool(c['cited'])})
    return {'id':row['id'],'role':row['role'],'content':row['content'],'created_at':row['created_at'],'mode':row['mode'],
            'model':row['model'],'refused':bool(row['refused']),
            'confidence':{'level':row['confidence_level'],'score':row['confidence_score']} if row['confidence_level'] else None,
            'citations':citations,'faithfulness':json.loads(row['faithfulness_json']) if row['faithfulness_json'] else None,
            'tokens':row['tokens'],'latency_ms':row['latency_ms']}

def check_doc_ids(db,ids):
    for doc_id in set(ids):
        if not db.execute('SELECT 1 FROM documents WHERE id=?',(doc_id,)).fetchone(): raise PaperWiseError('NOT_FOUND','Document not found.',404)

def set_docs(db,chat_id,ids):
    check_doc_ids(db,ids)
    db.execute('DELETE FROM chat_documents WHERE chat_id=?',(chat_id,))
    db.executemany('INSERT INTO chat_documents(chat_id,doc_id) VALUES (?,?)',[(chat_id,d) for d in dict.fromkeys(ids)])

@router.post('/chats')
def create_chat(body:CreateChat):
    chat_id=str(uuid.uuid4());stamp=now()
    with connect() as db:
        db.execute('INSERT INTO chats(id,title,created_at,updated_at) VALUES (?,?,?,?)',(chat_id,body.title,stamp,stamp))
        set_docs(db,chat_id,body.doc_ids)
        return render_chat(db,find_chat(db,chat_id))

@router.get('/chats')
def list_chats():
    with connect() as db: return [render_chat(db,r) for r in db.execute('SELECT * FROM chats ORDER BY updated_at DESC').fetchall()]

@router.get('/chats/{chat_id}')
def get_chat(chat_id:str):
    with connect() as db: return render_chat(db,find_chat(db,chat_id),True)

@router.patch('/chats/{chat_id}')
def patch_chat(chat_id:str,body:PatchChat):
    updates=body.model_dump(exclude_unset=True)
    with connect() as db:
        find_chat(db,chat_id)
        if 'doc_ids' in updates:
            if updates['doc_ids'] is None: raise PaperWiseError('VALIDATION_ERROR','doc_ids cannot be null.',422)
            set_docs(db,chat_id,updates.pop('doc_ids'))
        if 'pinned' in updates and updates['pinned'] is None: raise PaperWiseError('VALIDATION_ERROR','pinned cannot be null.',422)
        for key,value in updates.items(): db.execute(f'UPDATE chats SET {key}=? WHERE id=?',(value,chat_id))
        db.execute('UPDATE chats SET updated_at=? WHERE id=?',(now(),chat_id))
        return render_chat(db,find_chat(db,chat_id))

@router.delete('/chats/{chat_id}')
async def delete_chat(chat_id:str,request:Request):
    with connect() as db:
        find_chat(db,chat_id);db.execute('DELETE FROM chats WHERE id=?',(chat_id,))
    from app.core.chats.similar import delete_chat_vectors
    await asyncio.to_thread(delete_chat_vectors,chat_id)
    await request.app.state.jobs.maybe_recluster()
    return {'ok':True}

@router.get('/chats/{chat_id}/export')
def export_chat(chat_id:str,format:str='md'):
    if format!='md': raise PaperWiseError('VALIDATION_ERROR','Only Markdown export is supported.',422)
    with connect() as db:
        chat=render_chat(db,find_chat(db,chat_id),True)
    parts=['# '+(chat['title'] or 'Chat'),'Date: '+chat['updated_at']]
    with connect() as db:
        if chat['doc_ids']:
            marks=','.join('?' for _ in chat['doc_ids'])
            titles=[r[0] for r in db.execute(f'SELECT COALESCE(title,filename) FROM documents WHERE id IN ({marks})',chat['doc_ids'])]
        else: titles=[]
    parts.append('Active documents: '+(', '.join(titles) if titles else 'None'))
    for m in chat['messages']:
        parts += ['\n## '+m['role'].capitalize(),m['content']]
        if m['citations']:
            parts.append('\n'+'\n'.join(f"- [{c['marker']}] {c['doc_title']} — {c['location_label']}" + (' (source removed)' if c['chunk_id'] is None else '') for c in m['citations']))
    return PlainTextResponse('\n\n'.join(parts),media_type='text/markdown')

@router.get('/chats/{chat_id}/messages/{mid}',response_model=MessageResponse)
def message(chat_id:str,mid:str):
    with connect() as db:
        row=db.execute('SELECT * FROM messages WHERE id=? AND chat_id=?',(mid,chat_id)).fetchone()
        if row is None: raise PaperWiseError('NOT_FOUND','Message not found.',404)
        return render_message(db,row)

@router.get('/chats/{chat_id}/messages/{mid}/debug')
def message_debug(chat_id:str,mid:str):
    with connect() as db: row=db.execute('SELECT debug_json FROM messages WHERE id=? AND chat_id=?',(mid,chat_id)).fetchone()
    if row is None: raise PaperWiseError('NOT_FOUND','Message not found.',404)
    return json.loads(row['debug_json']) if row['debug_json'] else {'expanded_query':None,'retrieved':[],'final_prompt':None,'context_trimmed':False,'warnings':[],'timings_ms':{}}

@router.post('/chats/{chat_id}/messages/{mid}/stop')
async def stop(chat_id:str,mid:str,request:Request):
    generation=request.app.state.generations.get(mid)
    if not generation or generation.chat_id!=chat_id: raise PaperWiseError('NOT_FOUND','Active generation not found.',404)
    generation.stop()
    return {'stopped':True}

def sse(event,data): return f'event: {event}\ndata: {json.dumps(data,ensure_ascii=False)}\n\n'
def compare_mode(mode,question,doc_ids):
    return mode=='compare' or (mode=='auto' and len(doc_ids)>=2 and bool(re.search(r'\b(compare|comparison|difference|differences|differ|versus|vs\.?|contrast)\b',question,re.I)))

def get_retrieval(question,docs,top_k,compare):
    if not compare: return retrieve(question,docs,top_k)
    per_doc=max(2,top_k//len(docs)); batches=[retrieve(question,[d],per_doc) for d in docs]
    return {'expanded_query':batches[0]['expanded_query'],'retrieved':[item for b in batches for item in b['retrieved']],
            'candidates':sum(b['candidates'] for b in batches),'reranked':any(b['reranked'] for b in batches),
            'warnings':[w for b in batches for w in b['warnings']]}

def citation(item,marker):
    c=item['chunk']
    return {'marker':marker,'chunk_id':c['id'],'doc_id':c['doc_id'],'doc_title':c['title'] or c['filename'],
            'location_label':c['location_label'],'page':c['page'],'bboxes':c['bboxes'] if c['page'] is not None else None,
            'snippet':c['text'][:300],'highlight_span':None,'score':item['cosine'],'cited':False}

def save_result(mid,content,refused,confidence,tokens,latency,debug,citations):
    found,invalid=cited_markers(content,len(citations))
    if invalid: debug['warnings'].append('invalid_citation_markers: '+','.join(map(str,invalid)))
    with connect() as db:
        db.execute('UPDATE messages SET content=?,refused=?,confidence_level=?,confidence_score=?,tokens=?,latency_ms=?,debug_json=? WHERE id=?',
                   (content,int(refused),confidence['level'] if confidence else None,confidence['score'] if confidence else None,tokens,latency,json.dumps(debug),mid))
        for n in found: db.execute('UPDATE message_citations SET cited=1 WHERE message_id=? AND marker=?',(mid,n))

@router.post('/chats/{chat_id}/messages',response_class=StreamingResponse,responses={200:{'description':'Server-sent events, each framed as event and JSON data. Ordered events: retrieval {message_id,expanded_query,candidates,reranked,context_trimmed}, citations [Citation], token {text}, confidence {level,score}, done {message_id,model,tokens,latency_ms,refused}, optionally faithfulness {message_id,sentences:[{start,end,label,chunk_ids}]}. On failure: error {code,message,retryable}.', 'content':{'text/event-stream':{'schema':{'type':'string'}}}}})
async def send_message(chat_id:str,body:SendMessage,request:Request):
    if not body.question.strip(): raise PaperWiseError('VALIDATION_ERROR','Question cannot be blank.',422)
    with connect() as db:
        chat=find_chat(db,chat_id)
        ids=body.doc_ids if body.doc_ids is not None else [r[0] for r in db.execute('SELECT doc_id FROM chat_documents WHERE chat_id=? ORDER BY doc_id',(chat_id,))]
    ids=list(dict.fromkeys(ids));validate_documents(ids)
    settings=current_settings();model=body.model or chat['model'] or settings['default_model'];top_k=body.top_k or settings['top_k']
    compare=compare_mode(body.mode,body.question,ids);mode='compare' if compare else 'qa'
    mid=str(uuid.uuid4()); user_id=str(uuid.uuid4());stamp=now()
    with connect() as db:
        first_message=not bool(db.execute("SELECT 1 FROM messages WHERE chat_id=? AND role='user' LIMIT 1",(chat_id,)).fetchone())
        set_title=first_message and not chat['title']
        fallback=chat['title'] or body.question.strip()[:40]
        if set_title: db.execute('UPDATE chats SET title=? WHERE id=?',(fallback,chat_id))
        db.execute("INSERT INTO messages(id,chat_id,role,content,created_at) VALUES (?,?,?,?,?)",(user_id,chat_id,'user',body.question,stamp))
        db.execute("INSERT INTO messages(id,chat_id,role,content,mode,model,created_at) VALUES (?,?,?,?,?,?,?)",(mid,chat_id,'assistant','',mode,model,now()))
        db.execute('UPDATE chats SET updated_at=? WHERE id=?',(now(),chat_id))
    await request.app.state.jobs.enqueue('question_embed',{'chat_id':chat_id,'message_id':user_id,'question':body.question},9)
    control=Generation(chat_id);request.app.state.generations[mid]=control
    async def stream():
        started=time.monotonic();content='';tokens=0;confidence=None;citations=[];refused=False;successful=False;lock_acquired=False;agen=None;disconnected=False
        debug={'expanded_query':None,'retrieved':[],'final_prompt':None,'context_trimmed':False,'warnings':[],'timings_ms':{}}
        try:
            retrieval_start=time.monotonic()
            control.pending=asyncio.create_task(asyncio.to_thread(get_retrieval,body.question,ids,top_k,compare))
            while not control.pending.done():
                await asyncio.wait({control.pending},timeout=15)
                if not control.pending.done(): yield ': keep-alive\n\n'
            if control.stopped: return
            result=await control.pending
            debug['timings_ms']['retrieval']=round((time.monotonic()-retrieval_start)*1000)
            messages,ranked,trimmed=assemble(body.question,result['retrieved'],settings['num_ctx'],config.LLM_MAX_NEW_TOKENS,compare)
            citations=[citation(item,i) for i,item in enumerate(ranked,1)]
            confidence=evidence_match(item['cosine'] for item in ranked)
            debug.update(expanded_query=result['expanded_query'],final_prompt=messages,context_trimmed=trimmed,warnings=result['warnings'])
            debug['retrieved']=[{'chunk_id':x['chunk']['id'],'doc_id':x['chunk']['doc_id'],'location_label':x['chunk']['location_label'],
                'hybrid_score':x['hybrid_score'],'rerank_score':x['rerank_score'],'cosine':x['cosine'],'rank':i,'text':x['chunk']['text']} for i,x in enumerate(ranked,1)]
            with connect() as db:
                for c in citations:
                    db.execute('''INSERT INTO message_citations(message_id,marker,chunk_id,cited,score,doc_title,location_label,page,snippet,bboxes_json)
                                  VALUES (?,?,?,?,?,?,?,?,?,?)''', (mid,c['marker'],c['chunk_id'],0,c['score'],c['doc_title'],c['location_label'],c['page'],c['snippet'],json.dumps(c['bboxes']) if c['bboxes'] is not None else None))
                db.execute('UPDATE messages SET debug_json=? WHERE id=?',(json.dumps(debug),mid))
            yield sse('retrieval',{'message_id':mid,'expanded_query':result['expanded_query'],'candidates':result['candidates'],'reranked':result['reranked'],'context_trimmed':trimmed})
            yield sse('citations',citations)
            if not ranked:
                refused=True;content=PREFIX;tokens=1
                yield sse('token',{'text':content})
            else:
                wait_start=time.monotonic()
                request.app.state.interactive_waiters+=1
                try:
                    control.pending=asyncio.create_task(request.app.state.llm_lock.acquire())
                    while not control.pending.done():
                        await asyncio.wait({control.pending},timeout=15)
                        if not control.pending.done(): yield ': keep-alive\n\n'
                    await control.pending;lock_acquired=True
                finally:
                    request.app.state.interactive_waiters-=1
                if control.stopped: raise asyncio.CancelledError
                debug['timings_ms']['llm_queue_wait']=round((time.monotonic()-wait_start)*1000)
                provider=request.app.state.llm_provider
                agen=provider.stream(messages,model=model,temperature=config.LLM_TEMPERATURE,num_ctx=settings['num_ctx'],max_tokens=config.LLM_MAX_NEW_TOKENS)
                buffer=RefusalBuffer()
                while True:
                    if control.stopped: break
                    control.pending=asyncio.create_task(anext(agen))
                    while not control.pending.done():
                        await asyncio.wait({control.pending},timeout=15)
                        if not control.pending.done(): yield ': keep-alive\n\n'
                    if control.stopped: break
                    try: part=await control.pending
                    except StopAsyncIteration: break
                    tokens+=1
                    out=buffer.feed(part)
                    if out: content+=out;yield sse('token',{'text':out})
                if not control.stopped:
                    rest=buffer.feed('',final=True);refused=buffer.refused
                    if rest: content+=rest;yield sse('token',{'text':rest})
            if control.stopped:
                debug['warnings'].append('interrupted');refused=False
            yield sse('confidence',confidence)
            latency=round((time.monotonic()-started)*1000)
            save_result(mid,content,refused,confidence,tokens,latency,debug,citations);successful=True
            # Release the generation lock before any background LLM-judge fallback.
            if lock_acquired:
                request.app.state.llm_lock.release();lock_acquired=False
            job_id=None;future=None
            if not refused and not control.stopped and content:
                job_id=await request.app.state.jobs.enqueue('faithfulness',{'message_id':mid},8)
                future=request.app.state.jobs.waiters.get(job_id)
            yield sse('done',{'message_id':mid,'model':model,'tokens':tokens,'latency_ms':latency,'refused':refused})
            if job_id:
                if future:
                    try:
                        data=await asyncio.wait_for(asyncio.shield(future),timeout=config.FAITHFULNESS_SSE_WAIT_S)
                        if data:yield sse('faithfulness',data)
                    except asyncio.TimeoutError:pass
        except asyncio.CancelledError:
            # stop() cancels only the pending operation; disconnect cancels the whole response.
            if control.stopped:
                debug['warnings'].append('interrupted')
                yield sse('confidence',confidence or {'level':'low','score':0.0})
                latency=round((time.monotonic()-started)*1000)
                save_result(mid,content,False,confidence,tokens,latency,debug,citations);successful=True
                yield sse('done',{'message_id':mid,'model':model,'tokens':tokens,'latency_ms':latency,'refused':False})
            else:
                disconnected=True
                raise
        except PaperWiseError as exc:
            debug['warnings'].append(exc.code)
            yield sse('error',{'code':exc.code,'message':exc.message,'retryable':exc.retryable})
        except Exception:
            log.exception('Answer generation failed')
            debug['warnings'].append('INTERNAL')
            yield sse('error',{'code':'INTERNAL','message':'An internal error occurred.','retryable':False})
        finally:
            if control.pending and not control.pending.done():
                control.pending.cancel()
                try: await control.pending
                except (asyncio.CancelledError,Exception): pass
            if agen is not None:
                try: await agen.aclose()
                except Exception: log.exception('Failed to close provider stream')
            if lock_acquired: request.app.state.llm_lock.release()
            if not successful:
                debug['warnings'].append('interrupted' if control.stopped or disconnected else 'incomplete')
                save_result(mid,content,False,confidence,tokens,round((time.monotonic()-started)*1000),debug,citations)
            if successful: request.app.state.jobs.schedule_chat_embedding(chat_id)
            if first_message:
                await request.app.state.jobs.enqueue('chat_title',{'chat_id':chat_id,'question':body.question,'fallback':fallback,'set_title':set_title},9)
            request.app.state.generations.pop(mid,None)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
