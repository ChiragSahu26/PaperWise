from typing import Any,Literal
from pydantic import BaseModel

class SimilarReasons(BaseModel):
    shared_topics:list[str]
    shared_docs:list[str]
class SimilarChat(BaseModel):
    chat_id:str
    title:str|None
    similarity:float
    reasons:SimilarReasons
class DuplicateMatch(BaseModel):
    chat_id:str
    message_id:str
    question:str
    similarity:float
class DuplicateResult(BaseModel):match:DuplicateMatch|None
class Topic(BaseModel):
    topic_id:str
    label:str|None
    chat_ids:list[str]
    doc_ids:list[str]
class JobId(BaseModel):job_id:str
class Job(BaseModel):
    id:str
    kind:str
    status:Literal['queued','running','done','failed']
    percent:float
    error:str|None=None
class Ok(BaseModel):ok:bool
class Note(BaseModel):
    id:str
    body_md:str
    tags:list[str]
    doc_id:str|None
    chat_id:str|None
    message_id:str|None
    anchor:dict[str,Any]|None
    created_at:str
    updated_at:str
class Citations(BaseModel):
    total:int|None
    influential:int|None
    last_12_months:int|None
    by_year:dict[str,int]|None
class Retraction(BaseModel):
    retracted:bool|None
    notice_url:str|None
class CodeRepo(BaseModel):
    url:str
    stars:int|None
    last_commit:str|None
class Trending(BaseModel):huggingface:bool|None
class EvidencePart(BaseModel):
    name:str
    level:Literal['high','medium','low']|None
    value:Any
    note:str
class Evidence(BaseModel):
    level:Literal['high','medium','low']|None
    parts:list[EvidencePart]
    note:str
class Source(BaseModel):
    name:str
    url:str|None
class Intelligence(BaseModel):
    online:bool
    identified:bool
    title:str|None
    authors:list[str]
    doi:str|None=None
    arxiv_id:str|None=None
    venue:str|None
    type:Literal['preprint','journal','conference']|None
    published:str|None
    age_bucket:Literal['new','recent','established','older']|None
    citations:Citations|None
    retraction:Retraction|None
    code:list[CodeRepo]|None
    trending:Trending|None
    evidence_strength:Evidence|None
    sources:list[Source]
    fetched_at:str|None
class ResourceItem(BaseModel):
    type:Literal['video','code','article','docs']
    title:str
    url:str
    source:str
class Concept(BaseModel):
    name:str
    items:list[ResourceItem]
class Resources(BaseModel):
    concepts:list[Concept]
    status:Literal['ready','pending']
