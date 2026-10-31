from fastapi import APIRouter, Request, Query
from pydantic import BaseModel, Field, ConfigDict
from app.db.session import connect
from app.errors import PaperWiseError
from app.core.chats.similar import similar_chats, duplicate
from app.core.chats.topics import list_topics
from app.schemas.extras import SimilarChat,DuplicateResult,Topic,JobId,Job,Ok
router=APIRouter()
class DuplicateQuestion(BaseModel):
    model_config=ConfigDict(extra='forbid')
    question:str=Field(min_length=1)
class Dismiss(BaseModel):
    model_config=ConfigDict(extra='forbid')
    other_chat_id:str

@router.post('/chats/check-duplicate',response_model=DuplicateResult)
def check_duplicate(body:DuplicateQuestion): return {'match':duplicate(body.question)}

@router.get('/chats/{chat_id}/similar',response_model=list[SimilarChat])
def similar(chat_id:str,limit:int=Query(default=5,ge=1,le=100)):return similar_chats(chat_id,limit)

@router.post('/chats/{chat_id}/similar/dismiss',response_model=Ok)
def dismiss(chat_id:str,body:Dismiss):
    with connect() as db:
        for cid in (chat_id,body.other_chat_id):
            if not db.execute('SELECT 1 FROM chats WHERE id=?',(cid,)).fetchone(): raise PaperWiseError('NOT_FOUND','Chat not found.',404)
        if chat_id==body.other_chat_id:raise PaperWiseError('VALIDATION_ERROR','Cannot dismiss the same chat.',422)
        db.execute('INSERT OR IGNORE INTO similar_dismissals(chat_id,other_chat_id) VALUES (?,?)',(chat_id,body.other_chat_id))
    return {'ok':True}

@router.get('/topics',response_model=list[Topic])
def topics():return list_topics()

@router.post('/topics/recompute',response_model=JobId)
async def recompute(request:Request):return {'job_id':await request.app.state.jobs.enqueue('topic_cluster',{},9)}

@router.get('/jobs/{job_id}',response_model=Job)
def job(job_id:str):
    with connect() as db:r=db.execute('SELECT id,kind,status,percent,error FROM jobs WHERE id=?',(job_id,)).fetchone()
    if not r:raise PaperWiseError('NOT_FOUND','Job not found.',404)
    return dict(r)
