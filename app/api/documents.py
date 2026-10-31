import asyncio, hashlib, json, mimetypes, os, re, shutil, tempfile, uuid
from pathlib import Path
from fastapi import APIRouter, File, UploadFile, Request
from fastapi.responses import FileResponse, StreamingResponse
import config
from app.db.session import connect
from app.errors import PaperWiseError
from app.jobs.queue import now
from app.jobs.locks import document_lock
from app.core.ingestion.readers import sniff

router=APIRouter()

def get_doc(doc_id):
    with connect() as db: row=db.execute('SELECT * FROM documents WHERE id=?',(doc_id,)).fetchone()
    if row is None: raise PaperWiseError('NOT_FOUND','Document not found.',404)
    return row

def render(row,full=False):
    data={'id':row['id'],'filename':row['filename'],'file_type':row['file_type'],'status':row['status'],
          'page_count':row['page_count'],'title':row['title'],'authors':json.loads(row['authors_json'] or '[]'),
          'added_at':row['added_at'],'warnings':json.loads(row['warnings_json'] or '[]'),'intelligence_badge':None}
    from app.api.settings import current_settings
    if current_settings()['online_lookups']:
        with connect() as db: badge=db.execute('SELECT data_json FROM paper_intel WHERE doc_id=?',(row['id'],)).fetchone()
        if badge:
            intel=json.loads(badge[0]);data['intelligence_badge']={'age_bucket':intel.get('age_bucket'),'evidence_level':(intel.get('evidence_strength') or {}).get('level')}
    if full: data.update(abstract=row['abstract'],doi=row['doi'],arxiv_id=row['arxiv_id'],error=row['error'])
    return data

def safe_name(name):
    name=Path((name or '').replace('\\','/')).name
    name=re.sub(r'[^\w. -]','_',name,flags=re.UNICODE).strip('. ')
    return name[:200] or 'upload'

@router.post('/documents')
async def upload_documents(request: Request, files: list[UploadFile] = File(...)):
    if not files: raise PaperWiseError('VALIDATION_ERROR','No files were uploaded.',422)
    queue=request.app.state.jobs
    results=[]
    async with queue.upload_lock:
        for upload in files:
            name=safe_name(upload.filename)
            target_dir=config.DATA_DIR/'uploads'; target_dir.mkdir(parents=True,exist_ok=True)
            ext=Path(name).suffix.lower()
            fd,tmp_name=tempfile.mkstemp(prefix='.incoming-',suffix=ext,dir=target_dir)
            temp=Path(tmp_name); digest=hashlib.sha256(); size=0
            try:
                with os.fdopen(fd,'wb') as f:
                    while block:=await upload.read(1024*1024):
                        size+=len(block)
                        if size>config.MAX_UPLOAD_BYTES: raise PaperWiseError('VALIDATION_ERROR','File exceeds the size limit.',400)
                        digest.update(block); f.write(block)
                try: file_type=await asyncio.to_thread(sniff,temp)
                except (ValueError, OSError): raise PaperWiseError('UNSUPPORTED_FILE','Unsupported or invalid file type.',400)
                with connect() as db: existing=db.execute('SELECT id,filename,status FROM documents WHERE sha256=?',(digest.hexdigest(),)).fetchone()
                if existing:
                    results.append({'doc_id':existing['id'],'filename':existing['filename'],'status':existing['status'],'warning':'Duplicate file; existing document returned.'})
                    continue
                doc_id=str(uuid.uuid4()); folder=target_dir/doc_id; folder.mkdir(); final=folder/name
                os.replace(temp,final)
                try:
                    with connect() as db:
                        db.execute('INSERT INTO documents(id,filename,file_path,file_type,status,added_at,sha256) VALUES (?,?,?,?,?,?,?)',
                                   (doc_id,name,str(final.resolve()),file_type,'queued',now(),digest.hexdigest()))
                    await queue.enqueue('ingest',{'doc_id':doc_id})
                except BaseException:
                    with connect() as db: db.execute('DELETE FROM documents WHERE id=?',(doc_id,))
                    shutil.rmtree(folder,ignore_errors=True); raise
                results.append({'doc_id':doc_id,'filename':name,'status':'queued'})
                queue.publish({'doc_id':doc_id,'status':'queued','percent':0,'message':'Queued'})
            finally:
                temp.unlink(missing_ok=True)
                await upload.close()
    return results

@router.get('/documents/events')
async def events(request: Request):
    queue=request.app.state.jobs; subscriber=asyncio.Queue(maxsize=100); queue.subscribers.add(subscriber)
    async def stream():
        try:
            while True:
                try:
                    item=await asyncio.wait_for(subscriber.get(),timeout=15)
                    yield 'event: progress\ndata: '+json.dumps(item,ensure_ascii=False)+'\n\n'
                except asyncio.TimeoutError: yield ': keep-alive\n\n'
                if subscriber not in queue.subscribers: return
        finally: queue.subscribers.discard(subscriber)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@router.get('/documents')
def list_documents():
    with connect() as db: rows=db.execute('SELECT * FROM documents ORDER BY added_at DESC').fetchall()
    return [render(r) for r in rows]

@router.get('/documents/{doc_id}')
def document(doc_id: str): return render(get_doc(doc_id),True)

@router.delete('/documents/{doc_id}')
async def delete(doc_id: str):
    def remove():
        with document_lock(doc_id):
            row=get_doc(doc_id)
            from app.core.retrieval.vector_store import delete_document
            delete_document(doc_id)
            with connect() as db:
                db.execute("UPDATE jobs SET status='failed',error='document deleted',updated_at=? WHERE kind='ingest' AND status='queued' AND json_extract(payload_json,'$.doc_id')=?",(now(),doc_id))
                from app.core.knowledge.graph import remove_contributions
                from app.core.knowledge.conflicts import recompute
                remove_contributions(db,doc_id)
                db.execute('UPDATE notes SET anchor_json=NULL WHERE doc_id=?',(doc_id,))
                db.execute('DELETE FROM documents WHERE id=?',(doc_id,))
                recompute(db)
            # Only remove the directory created for this document, never arbitrary DB paths.
            expected=(config.DATA_DIR/'uploads'/doc_id).resolve()
            if Path(row['file_path']).resolve().parent == expected:
                shutil.rmtree(expected,ignore_errors=True)
    await asyncio.to_thread(remove)
    return {'ok':True}

@router.get('/documents/{doc_id}/file')
def file(doc_id: str):
    row=get_doc(doc_id); path=Path(row['file_path'])
    if not path.is_file(): raise PaperWiseError('NOT_FOUND','File not found.',404)
    return FileResponse(path,media_type=mimetypes.guess_type(row['filename'])[0] or 'application/octet-stream',filename=row['filename'],content_disposition_type='inline')

@router.get('/documents/{doc_id}/chunks/{chunk_id}')
def chunk(doc_id: str, chunk_id: str):
    with connect() as db: r=db.execute('SELECT * FROM chunks WHERE doc_id=? AND id=?',(doc_id,chunk_id)).fetchone()
    if r is None: raise PaperWiseError('NOT_FOUND','Chunk not found.',404)
    return {'chunk_id':r['id'],'doc_id':r['doc_id'],'text':r['text'],'location_label':r['location_label'],'page':r['page'],
            'bboxes':json.loads(r['bboxes_json']) if r['bboxes_json'] else None,'type':r['type']}
