import json
from typing import Annotated
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
import config
from app.db.session import connect

router = APIRouter()
class Weights(BaseModel):
    model_config = ConfigDict(extra='forbid')
    semantic: float = Field(ge=0, le=1)
    bm25: float = Field(ge=0, le=1)
    @model_validator(mode='after')
    def sum_one(self):
        if abs(self.semantic + self.bm25 - 1) > 1e-6: raise ValueError('hybrid weights must sum to 1')
        return self
class SimilarityWeights(BaseModel):
    model_config = ConfigDict(extra='forbid')
    topic: float = Field(ge=0, le=1)
    docs: float = Field(ge=0, le=1)
    @model_validator(mode='after')
    def sum_one(self):
        if abs(self.topic + self.docs - 1) > 1e-6: raise ValueError('similarity weights must sum to 1')
        return self
class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    default_model: str | None = Field(default=None, min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)
    hybrid_weights: Weights | None = None
    use_reranker: bool | None = None
    num_ctx: int | None = Field(default=None, ge=1)
    online_lookups: bool | None = None
    similarity_weights: SimilarityWeights | None = None
    notes_in_retrieval: bool | None = None

def defaults():
    return {'default_model': config.LLM_MODEL, 'top_k': config.TOP_K_DEFAULT,
            'hybrid_weights': {'semantic':config.HYBRID_W_SEMANTIC,'bm25':config.HYBRID_W_BM25},
            'use_reranker':config.USE_RERANKER, 'num_ctx':config.LLM_NUM_CTX,
            'online_lookups':config.ALLOW_ONLINE_LOOKUPS,
            'similarity_weights':{'topic':config.SIM_W_TOPIC,'docs':config.SIM_W_DOCS},
            'notes_in_retrieval':False}

def current_settings():
    result = defaults()
    with connect() as db:
        result.update({r['key']: json.loads(r['value_json']) for r in db.execute('SELECT key,value_json FROM settings') if r['key'] in result})
    return result

@router.get('/settings')
def get_settings():
    return current_settings()

@router.put('/settings')
async def put_settings(update: SettingsUpdate, request: Request):
    values = update.model_dump(exclude_unset=True)
    if any(v is None for v in values.values()):
        from app.errors import PaperWiseError
        raise PaperWiseError('VALIDATION_ERROR','Setting values cannot be null.',422)
    previous=current_settings()
    with connect() as db:
        db.executemany('INSERT INTO settings(key,value_json) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json', [(k,json.dumps(v)) for k,v in values.items()])
    if values.get('notes_in_retrieval') is True and not previous['notes_in_retrieval']:
        await request.app.state.jobs.enqueue('notes_reindex',{},9)
    return current_settings()
