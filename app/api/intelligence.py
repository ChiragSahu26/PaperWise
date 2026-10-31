import json,re
from datetime import datetime,timezone,timedelta
from fastapi import APIRouter,Request
from pydantic import BaseModel,ConfigDict,model_validator
from app.api.documents import get_doc
from app.core.intelligence import online
from app.core.intelligence.resolve import intelligence,offline
from app.db.session import connect
from app.jobs.queue import now
from app.schemas.extras import Intelligence,Resources
router=APIRouter()

class Identify(BaseModel):
    model_config=ConfigDict(extra='forbid')
    doi:str|None=None
    arxiv_id:str|None=None
    @model_validator(mode='after')
    def valid(self):
        if not self.doi and not self.arxiv_id:raise ValueError('doi or arxiv_id is required')
        if self.doi and not re.fullmatch(r'10\.\d{4,9}/[^\s<>"\[\]]+',self.doi,re.I):raise ValueError('Invalid DOI')
        if self.arxiv_id and not re.fullmatch(r'(?:arxiv:)?\d{4}\.\d{4,5}(?:v\d+)?',self.arxiv_id,re.I):raise ValueError('Invalid arXiv ID')
        return self

def fresh(timestamp,days):
    try:return datetime.now(timezone.utc)-datetime.fromisoformat(timestamp.replace('Z','+00:00'))<timedelta(days=days)
    except (ValueError,TypeError):return False

@router.get('/documents/{doc_id}/intelligence',response_model=Intelligence)
async def paper_intelligence(doc_id:str,refresh:bool=False):
    row=get_doc(doc_id)
    if not online.enabled():return offline(row)
    with connect() as db:cached=db.execute('SELECT * FROM paper_intel WHERE doc_id=?',(doc_id,)).fetchone()
    if cached and not refresh and fresh(cached['fetched_at'],7):return json.loads(cached['data_json'])
    result=await intelligence(row,refresh)
    if result['online']:
        with connect() as db:
            db.execute('INSERT INTO paper_intel(doc_id,data_json,fetched_at) VALUES (?,?,?) ON CONFLICT(doc_id) DO UPDATE SET data_json=excluded.data_json,fetched_at=excluded.fetched_at',(doc_id,json.dumps(result),now()))
    return result

@router.post('/documents/{doc_id}/identify',response_model=Intelligence)
async def identify(doc_id:str,body:Identify):
    get_doc(doc_id)
    with connect() as db:
        db.execute('UPDATE documents SET doi=COALESCE(?,doi),arxiv_id=COALESCE(?,arxiv_id) WHERE id=?',(body.doi,body.arxiv_id,doc_id))
        db.execute('DELETE FROM paper_intel WHERE doc_id=?',(doc_id,))
    return await paper_intelligence(doc_id,refresh=True)

@router.get('/documents/{doc_id}/resources',response_model=Resources)
async def resources(doc_id:str,request:Request,refresh:bool=False):
    get_doc(doc_id)
    with connect() as db:
        row=db.execute('SELECT * FROM resources_cache WHERE doc_id=?',(doc_id,)).fetchone()
        active=db.execute("SELECT id FROM jobs WHERE kind='learn_resources' AND status IN ('queued','running') AND json_extract(payload_json,'$.doc_id')=?",(doc_id,)).fetchone()
    if row and not refresh and fresh(row['fetched_at'],30):return json.loads(row['data_json'])
    if not active:await request.app.state.jobs.enqueue('learn_resources',{'doc_id':doc_id},5)
    return {'concepts':[],'status':'pending'}
