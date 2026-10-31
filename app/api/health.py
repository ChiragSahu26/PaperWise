import httpx
from fastapi import APIRouter
import config
from app.api.settings import current_settings
from app.errors import PaperWiseError
router = APIRouter()

async def ollama_tags():
    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            response = await client.get(config.OLLAMA_URL + '/api/tags')
            response.raise_for_status()
            return response.json().get('models', [])
    except (httpx.HTTPError, ValueError):
        return None

def device():
    if config.DEVICE != 'auto': return config.DEVICE
    try:
        import torch
        if torch.backends.mps.is_available(): return 'mps'
    except ImportError: pass
    return 'cpu'

@router.get('/health')
async def health():
    models = await ollama_tags()
    enabled=current_settings()['online_lookups']
    if enabled:
        from app.core.intelligence.online import connectivity
        internet=await connectivity()
    else: internet=False
    return {'status':'ok','version':'0.1.0','ollama':{'up':models is not None,'models':[m.get('name','') for m in models or []]},
            'internet':internet, 'online_lookups_enabled':enabled, 'device':device()}

@router.get('/models')
async def models():
    models = await ollama_tags()
    if models is None:
        raise PaperWiseError('OLLAMA_UNAVAILABLE','Ollama is not running.',503,True,'Start Ollama and retry.')
    return [{'name':m.get('name'), 'size_gb':round(m.get('size',0)/1_000_000_000,2), 'family':(m.get('details') or {}).get('family'),
             'params':(m.get('details') or {}).get('parameter_size'), 'quant':(m.get('details') or {}).get('quantization_level')} for m in models]
