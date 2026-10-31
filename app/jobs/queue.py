"""Persisted priority queues: two ingestion/embedding workers and one LLM worker."""
import asyncio, json, logging, uuid, threading
from datetime import datetime, timezone
from contextlib import suppress
from app.db.session import connect

log=logging.getLogger(__name__)
def now(): return datetime.now(timezone.utc).isoformat()
LLM_KINDS={'chat_title','topic_cluster','learn_resources','extract_knowledge'}

class JobQueue:
    def __init__(self,app=None):
        self.app=app; self.queue=asyncio.PriorityQueue();self.llm_queue=asyncio.PriorityQueue()
        self.subscribers=set();self.workers=[];self.sequence=0;self.loop=None
        self.upload_lock=asyncio.Lock();self.debounce={};self.waiters={}
    async def start(self):
        self.loop=asyncio.get_running_loop()
        import config
        if (config.DATA_DIR/'chroma').exists():
            from app.core.retrieval.vector_store import recover_interrupted_ingests
            await asyncio.to_thread(recover_interrupted_ingests)
        with connect() as db:
            db.execute("UPDATE documents SET status='failed',error='interrupted' WHERE id IN (SELECT json_extract(payload_json,'$.doc_id') FROM jobs WHERE status='running' AND kind='ingest')")
            db.execute("UPDATE jobs SET status='failed',error='interrupted',updated_at=? WHERE status='running'",(now(),))
            queued=list(db.execute("SELECT id,kind,priority,payload_json FROM jobs WHERE status='queued' ORDER BY created_at"))
        for row in queued: await self._put(row['id'],row['kind'],row['priority'],json.loads(row['payload_json']))
        self.workers=[asyncio.create_task(self.worker(self.queue)) for _ in range(2)]+[asyncio.create_task(self.worker(self.llm_queue))]
    async def close(self):
        for task in self.debounce.values(): task.cancel()
        for t in self.workers:t.cancel()
        for t in self.workers:
            with suppress(asyncio.CancelledError):await t
    async def _put(self,job_id,kind,priority,payload):
        self.sequence+=1
        await (self.llm_queue if kind in LLM_KINDS else self.queue).put((priority,self.sequence,job_id,kind,payload))
    async def enqueue(self,kind,payload,priority=3):
        job_id=str(uuid.uuid4());stamp=now()
        with connect() as db:
            db.execute('INSERT INTO jobs(id,kind,status,percent,payload_json,priority,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                       (job_id,kind,'queued',0,json.dumps(payload),priority,stamp,stamp))
        if kind=='faithfulness':
            future=asyncio.get_running_loop().create_future();self.waiters[job_id]=future
            future.add_done_callback(lambda _f:self.waiters.pop(job_id,None))
        await self._put(job_id,kind,priority,payload);return job_id
    def schedule_chat_embedding(self,chat_id):
        old=self.debounce.pop(chat_id,None)
        if old:old.cancel()
        async def delayed():
            try:
                await asyncio.sleep(3)
                await self.enqueue('chat_embed',{'chat_id':chat_id},9)
            finally:
                if self.debounce.get(chat_id) is asyncio.current_task(): self.debounce.pop(chat_id,None)
        self.debounce[chat_id]=asyncio.create_task(delayed())
    def publish(self,event):
        for q in tuple(self.subscribers):
            try:q.put_nowait(event)
            except asyncio.QueueFull:self.subscribers.discard(q)
    def progress_threadsafe(self,event):self.loop.call_soon_threadsafe(self.publish,event)
    async def maybe_recluster(self):
        from app.core.chats.similar import chats_collection
        import config
        with connect() as db:
            count=db.execute('SELECT COUNT(*) FROM chats').fetchone()[0]
            settings={r['key']:json.loads(r['value_json']) for r in db.execute("SELECT key,value_json FROM settings WHERE key IN ('topic_last_count','topic_last_indexed')")}
            active=db.execute("SELECT 1 FROM jobs WHERE kind='topic_cluster' AND status IN ('queued','running') LIMIT 1").fetchone()
        indexed=await asyncio.to_thread(lambda:chats_collection().count())
        if (abs(count-settings.get('topic_last_count',0))>=config.TOPIC_RECLUSTER_DELTA or
            abs(indexed-settings.get('topic_last_indexed',0))>=config.TOPIC_RECLUSTER_DELTA) and not active:
            await self.enqueue('topic_cluster',{},9)

    async def background_complete(self,prompt,json_schema=None,system=None):
        # Interactive waiters win between separate background LLM calls.
        while self.app.state.llm_lock.locked() or self.app.state.interactive_waiters:
            await asyncio.sleep(.05)
        async with self.app.state.llm_lock:
            from app.api.settings import current_settings
            import config
            opts=current_settings()
            messages=([{'role':'system','content':system}] if system else [])+[{'role':'user','content':prompt}]
            stream=self.app.state.llm_provider.stream(messages,model=opts['default_model'],temperature=config.LLM_TEMPERATURE,num_ctx=opts['num_ctx'],max_tokens=512,json_schema=json_schema)
            return ''.join([x async for x in stream]).strip()
    async def safe_thread(self,func,*args):
        task=asyncio.create_task(asyncio.to_thread(func,*args))
        try:return await asyncio.shield(task)
        except asyncio.CancelledError:
            with suppress(Exception):await task
            raise

    async def worker(self,queue):
        while True:
            _,_,job_id,kind,payload=await queue.get()
            try:
                with connect() as db:
                    if not db.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=? AND status='queued'",(now(),job_id)).rowcount:continue
                if kind=='ingest':
                    from app.jobs.ingest import ingest_document
                    from app.jobs.locks import document_lock
                    cancelled=threading.Event()
                    def run_locked():
                        with document_lock(payload['doc_id']):ingest_document(payload['doc_id'],job_id,self.progress_threadsafe,cancelled)
                    task=asyncio.create_task(asyncio.to_thread(run_locked))
                    try:await asyncio.shield(task)
                    except asyncio.CancelledError:
                        cancelled.set()
                        with suppress(Exception):await task
                        with connect() as db:
                            db.execute("UPDATE jobs SET status='failed',error='interrupted',updated_at=? WHERE id=? AND status='running'",(now(),job_id))
                            db.execute("UPDATE documents SET status='failed',error='interrupted' WHERE id=? AND status!='ready'",(payload['doc_id'],))
                        raise
                    with connect() as db:
                        ready=db.execute("SELECT 1 FROM documents WHERE id=? AND status='ready'",(payload['doc_id'],)).fetchone()
                    if ready:await self.enqueue('extract_knowledge',{'doc_id':payload['doc_id']},7)
                elif kind=='similarity_check':
                    from app.core.checks.similarity import run_check
                    await self.safe_thread(run_check,payload['report_id'],payload)
                elif kind=='faithfulness':
                    from app.core.checks.faithfulness import check_answer
                    result=await check_answer(self,payload['message_id'])
                    future=self.waiters.get(job_id)
                    if future and not future.done():future.set_result(result)
                elif kind=='note_embed':
                    from app.core.notes.index import index_note
                    await self.safe_thread(index_note,payload['note_id'])
                elif kind=='notes_reindex':
                    from app.core.notes.index import reindex
                    await self.safe_thread(reindex)
                elif kind=='question_embed':
                    from app.core.chats.similar import index_question
                    await self.safe_thread(index_question,payload['chat_id'],payload['message_id'],payload['question'])
                elif kind=='chat_embed':
                    from app.core.chats.similar import update_chat_vector
                    await self.safe_thread(update_chat_vector,payload['chat_id'])
                    await self.maybe_recluster()
                elif kind=='chat_title':
                    chat_id=payload['chat_id'];question=payload['question'];fallback=payload['fallback']
                    title=await self.background_complete('Write a 3 to 6 word title for this conversation. Reply with only the title.\n\n'+question)
                    summary=await self.background_complete('Write a one-line summary of this conversation. Reply with only the summary.\n\n'+question)
                    title=' '.join(title.strip(' "\'\n').split()[:6]);summary=' '.join(summary.split())[:500]
                    if not 3<=len(title.split())<=6: title=fallback
                    with connect() as db:
                        db.execute('UPDATE chats SET title=CASE WHEN ? AND title=? THEN ? ELSE title END,summary=? WHERE id=?',(int(payload.get('set_title',True)),fallback,title or fallback,summary or None,chat_id))
                    self.schedule_chat_embedding(chat_id)
                elif kind=='extract_knowledge':
                    from app.core.knowledge.extract import extract_document
                    await extract_document(self,payload['doc_id'])
                elif kind=='learn_resources':
                    from app.core.intelligence.learn import build_resources
                    await build_resources(self,payload['doc_id'])
                elif kind=='topic_cluster':
                    from app.core.chats.topics import clusters,save_groups
                    groups=await self.safe_thread(clusters);labelled=[]
                    for group in groups:
                        prompt='Give a 2 to 4 word topic label for these chat titles. Reply with only the label.\n'+'\n'.join(title for _,title in group)
                        try:label=' '.join((await self.background_complete(prompt)).strip(' "\'\n').split()[:4])
                        except Exception:
                            log.warning('Topic label generation unavailable; using a title',exc_info=True)
                            label=' '.join(group[0][1].split()[:4])
                        if not 2<=len(label.split())<=4:label='Related chats'
                        labelled.append((group,label))
                    await self.safe_thread(save_groups,labelled)
                    with connect() as db:
                        count=db.execute('SELECT COUNT(*) FROM chats').fetchone()[0]
                        db.execute("INSERT INTO settings(key,value_json) VALUES ('topic_last_count',?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",(json.dumps(count),))
                        from app.core.chats.similar import chats_collection
                        indexed=chats_collection().count()
                        db.execute("INSERT INTO settings(key,value_json) VALUES ('topic_last_indexed',?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",(json.dumps(indexed),))
                else:raise ValueError('Unsupported job kind')
                if kind!='ingest':
                    with connect() as db:db.execute("UPDATE jobs SET status='done',percent=100,updated_at=? WHERE id=?",(now(),job_id))
            except asyncio.CancelledError:raise
            except Exception:
                log.exception('%s job %s failed',kind,job_id)
                future=self.waiters.get(job_id)
                if future and not future.done():future.set_result(None)
                with connect() as db:
                    db.execute("UPDATE jobs SET status='failed',error=?,updated_at=? WHERE id=?",(kind+' failed',now(),job_id))
                    if kind=='ingest':db.execute("UPDATE documents SET status='failed',error='Ingestion failed' WHERE id=?",(payload['doc_id'],))
                if kind=='ingest':self.publish({'doc_id':payload['doc_id'],'status':'failed','percent':0,'message':'Ingestion failed'})
            finally:queue.task_done()
