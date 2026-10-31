from fastapi import APIRouter
from pydantic import BaseModel
from app.core.knowledge.graph import get_graph,node_detail
from app.core.knowledge.conflicts import list_conflicts
router=APIRouter()
class GraphNode(BaseModel):
    id:str
    type:str
    label:str
    doc_ids:list[str]
class GraphEdge(BaseModel):
    id:str
    source:str
    target:str
    type:str
    chunk_ids:list[str]
class Graph(BaseModel):
    nodes:list[GraphNode]
    edges:list[GraphEdge]
class NodeDetail(BaseModel):
    node:GraphNode
    neighbors:list[GraphNode]
    passages:list[dict]
class ConflictEntry(BaseModel):
    doc_id:str
    value:float
    citation:dict
class Conflict(BaseModel):
    id:str
    dataset:str
    metric:str
    setting:str|None
    entries:list[ConflictEntry]
    note:str

def comma(value):return [x for x in value.split(',') if x] if value else None
@router.get('/graph',response_model=Graph)
def graph(doc_ids:str|None=None,node_types:str|None=None):return get_graph(comma(doc_ids),comma(node_types))
@router.get('/graph/nodes/{id}',response_model=NodeDetail)
def detail(id:str):return node_detail(id)
@router.get('/conflicts',response_model=list[Conflict])
def conflicts(doc_ids:str|None=None):return list_conflicts(comma(doc_ids))
