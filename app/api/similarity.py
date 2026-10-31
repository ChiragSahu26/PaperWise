import uuid
from typing import Literal
from fastapi import APIRouter,Request
from pydantic import BaseModel,model_validator
from app.db.session import connect
from app.errors import PaperWiseError
from app.jobs.queue import now

router=APIRouter()
class SimilarityRequest(BaseModel):
    mode:Literal['corpus','my_writing','web']
    doc_id:str|None=None
    text:str|None=None
    exclude_quotes:bool=True
    confirm_send:bool=False
    @model_validator(mode='after')
    def target(self):
        if self.mode=='corpus' and not self.doc_id:raise ValueError('doc_id is required in corpus mode')
        if self.mode=='my_writing' and not self.text:raise ValueError('text is required in my_writing mode')
        return self
class SimilarityCreated(BaseModel):
    job_id:str
    check_id:str

@router.post('/similarity-checks',response_model=SimilarityCreated)
async def create(body:SimilarityRequest,request:Request):
    if body.mode=='web':raise PaperWiseError('ONLINE_FEATURE_DISABLED','Web similarity is not configured.',403)
    if body.mode=='corpus':
        with connect() as db:doc=db.execute('SELECT status FROM documents WHERE id=?',(body.doc_id,)).fetchone()
        if not doc:raise PaperWiseError('NOT_FOUND','Document not found.',404)
        if doc['status']!='ready':raise PaperWiseError('DOCUMENT_NOT_READY','Document is not ready.',409)
    rid=str(uuid.uuid4());payload=body.model_dump();payload['scope']=payload.pop('mode');payload['text']=body.text if body.mode=='my_writing' else None
    if body.mode=='my_writing':payload['doc_id']=None
    with connect() as db:db.execute('INSERT INTO similarity_checks(id,scope,target_doc_id,target_text,result_json,created_at) VALUES (?,?,?,?,?,?)',(rid,body.mode,body.doc_id,payload['text'],None,now()))
    job=await request.app.state.jobs.enqueue('similarity_check',{'report_id':rid,**payload},9)
    return {'check_id':rid,'job_id':job}

class TextSpan(BaseModel):
    start:int
    end:int
class Match(BaseModel):
    text_span:TextSpan
    text:str
    source_doc_id:str
    source_citation:dict
    similarity:float
    kind:Literal['exact','paraphrase']
class SimilarityReport(BaseModel):
    overall_percent:float
    matches:list[Match]

@router.get('/similarity-checks/{id}',response_model=SimilarityReport)
def get(id:str):
    import json
    with connect() as db:row=db.execute('SELECT result_json FROM similarity_checks WHERE id=?',(id,)).fetchone()
    if not row:raise PaperWiseError('NOT_FOUND','Similarity report not found.',404)
    if row['result_json'] is None:raise PaperWiseError('DOCUMENT_NOT_READY','Similarity report is not ready.',409,retryable=True)
    return json.loads(row['result_json'])
