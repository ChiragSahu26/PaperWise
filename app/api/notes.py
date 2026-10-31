import asyncio,json,re,uuid
from typing import Any
from fastapi import APIRouter,Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel,ConfigDict,Field,field_validator,FiniteFloat
from app.db.session import connect
from app.jobs.queue import now
from app.errors import PaperWiseError
from app.core.notes.index import note_lock,remove_index
from app.api.settings import current_settings
from app.schemas.extras import Note,Ok

router=APIRouter()
class Anchor(BaseModel):
    model_config=ConfigDict(extra='forbid')
    page:int|None=Field(default=None,ge=1)
    bboxes:list[list[FiniteFloat]]|None=None
    quote:str|None=None
    @field_validator('bboxes')
    @classmethod
    def valid_boxes(cls,value):
        if value is not None:
            for b in value:
                if len(b)!=4 or b[2]<=b[0] or b[3]<=b[1]:raise ValueError('Each bounding box must be [x0,y0,x1,y1] with positive area')
        return value
class NoteCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    body_md:str=Field(min_length=1)
    tags:list[str]=Field(default_factory=list)
    doc_id:str|None=None
    chat_id:str|None=None
    message_id:str|None=None
    anchor:Anchor|None=None
class NotePatch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    body_md:str|None=Field(default=None,min_length=1)
    tags:list[str]|None=None
    doc_id:str|None=None
    chat_id:str|None=None
    message_id:str|None=None
    anchor:Anchor|None=None

def render(r):
    return {'id':r['id'],'body_md':r['body_md'],'tags':json.loads(r['tags_json'] or '[]'),'doc_id':r['doc_id'],
            'chat_id':r['chat_id'],'message_id':r['message_id'],'anchor':json.loads(r['anchor_json']) if r['anchor_json'] else None,
            'created_at':r['created_at'],'updated_at':r['updated_at']}

def validate_refs(db,values):
    for field,table in [('doc_id','documents'),('chat_id','chats'),('message_id','messages')]:
        if values.get(field) and not db.execute(f'SELECT 1 FROM {table} WHERE id=?',(values[field],)).fetchone():raise PaperWiseError('NOT_FOUND',f'{field} not found.',404)
    if values.get('anchor'):
        if not values.get('doc_id'):raise PaperWiseError('VALIDATION_ERROR','PDF anchors require a document.',422)
        doc=db.execute('SELECT file_type,page_count FROM documents WHERE id=?',(values['doc_id'],)).fetchone()
        if doc['file_type']!='pdf':raise PaperWiseError('VALIDATION_ERROR','A passage anchor requires a PDF.',422)
        if values['anchor'].get('page') and doc['page_count'] and values['anchor']['page']>doc['page_count']:raise PaperWiseError('VALIDATION_ERROR','Anchor page is outside the PDF.',422)
    if values.get('message_id') and values.get('chat_id'):
        if not db.execute('SELECT 1 FROM messages WHERE id=? AND chat_id=?',(values['message_id'],values['chat_id'])).fetchone():raise PaperWiseError('VALIDATION_ERROR','Message does not belong to chat.',422)

def note_query(doc_id=None,chat_id=None,tag=None,q=None):
    clauses=[];params=[];join=''
    if q:
        words=re.findall(r'\w+',q,flags=re.UNICODE)
        if not words:return []
        join=' JOIN notes_fts ON notes_fts.rowid=n.rowid'
        clauses.append('notes_fts MATCH ?');params.append(' AND '.join('"'+w.replace('"','""')+'"' for w in words))
    if doc_id:clauses.append('n.doc_id=?');params.append(doc_id)
    if chat_id:clauses.append('n.chat_id=?');params.append(chat_id)
    if tag:clauses.append('EXISTS (SELECT 1 FROM json_each(n.tags_json) WHERE value=?)');params.append(tag)
    sql='SELECT n.* FROM notes n'+join+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY n.updated_at DESC,n.id'
    with connect() as db:return [render(r) for r in db.execute(sql,params)]

@router.get('/notes',response_model=list[Note])
def list_notes(doc_id:str|None=None,chat_id:str|None=None,tag:str|None=None,q:str|None=None):return note_query(doc_id,chat_id,tag,q)

@router.get('/notes/export')
def export_notes(format:str='md'):
    if format!='md':raise PaperWiseError('VALIDATION_ERROR','Only Markdown export is supported.',422)
    items=note_query();parts=['# Notes']
    for item in items:
        parts.extend(['\n## '+item['created_at'],item['body_md'],'Tags: '+', '.join(item['tags'])])
        if item['anchor']:parts.append('Anchor: '+json.dumps(item['anchor'],ensure_ascii=False))
    return PlainTextResponse('\n\n'.join(parts),media_type='text/markdown')

@router.post('/notes',response_model=Note)
async def create_note(body:NoteCreate,request:Request):
    data=body.model_dump();nid=str(uuid.uuid4());stamp=now()
    def persist():
        with note_lock,connect() as db:
            validate_refs(db,data)
            db.execute('INSERT INTO notes(id,body_md,tags_json,doc_id,chat_id,message_id,anchor_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                       (nid,data['body_md'],json.dumps(data['tags']),data['doc_id'],data['chat_id'],data['message_id'],json.dumps(data['anchor']) if data['anchor'] is not None else None,stamp,stamp))
            return render(db.execute('SELECT * FROM notes WHERE id=?',(nid,)).fetchone())
    row=await asyncio.to_thread(persist)
    if current_settings()['notes_in_retrieval']:await request.app.state.jobs.enqueue('note_embed',{'note_id':nid},9)
    return row

@router.patch('/notes/{note_id}',response_model=Note)
async def update_note(note_id:str,body:NotePatch,request:Request):
    patch=body.model_dump(exclude_unset=True)
    if ('body_md' in patch and patch['body_md'] is None) or ('tags' in patch and patch['tags'] is None):raise PaperWiseError('VALIDATION_ERROR','body_md and tags cannot be null.',422)
    def persist():
        with note_lock,connect() as db:
            row=db.execute('SELECT * FROM notes WHERE id=?',(note_id,)).fetchone()
            if not row:raise PaperWiseError('NOT_FOUND','Note not found.',404)
            values=render(row);values.update(patch);validate_refs(db,values)
            db.execute('UPDATE notes SET body_md=?,tags_json=?,doc_id=?,chat_id=?,message_id=?,anchor_json=?,updated_at=? WHERE id=?',
                       (values['body_md'],json.dumps(values['tags']),values['doc_id'],values['chat_id'],values['message_id'],json.dumps(values['anchor']) if values['anchor'] is not None else None,now(),note_id))
            return render(db.execute('SELECT * FROM notes WHERE id=?',(note_id,)).fetchone())
    result=await asyncio.to_thread(persist)
    if current_settings()['notes_in_retrieval']:await request.app.state.jobs.enqueue('note_embed',{'note_id':note_id},9)
    return result

@router.delete('/notes/{note_id}',response_model=Ok)
def delete_note(note_id:str):
    with note_lock:
        with connect() as db:
            if not db.execute('DELETE FROM notes WHERE id=?',(note_id,)).rowcount:raise PaperWiseError('NOT_FOUND','Note not found.',404)
        remove_index(note_id)
    return {'ok':True}
