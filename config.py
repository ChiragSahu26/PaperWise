"""Environment defaults. Settings marked in the spec can also be changed through the API."""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
def env(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    if isinstance(default, bool):
        if value.lower() not in ('true','false','1','0','yes','no'):
            raise ValueError(f'Invalid boolean for {name}')
        return value.lower() in ('true','1','yes')
    if isinstance(default, list):
        return json.loads(value)
    return type(default)(value) if default is not None else value

EMBEDDING_MODEL = env('EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2')
RERANK_MODEL = env('RERANK_MODEL', 'cross-encoder/ms-marco-MiniLM-L-6-v2')
HYBRID_W_SEMANTIC = env('HYBRID_W_SEMANTIC', 0.65)
HYBRID_W_BM25 = env('HYBRID_W_BM25', 0.35)
RERANK_SHORTLIST = env('RERANK_SHORTLIST', 10)
TOP_K_DEFAULT = env('TOP_K_DEFAULT', 6)
CANDIDATE_POOL = env('CANDIDATE_POOL', 50)
USE_RERANKER = env('USE_RERANKER', True)
CHUNK_SIZE_PDF = env('CHUNK_SIZE_PDF', 1000)
CHUNK_OVERLAP_PDF = env('CHUNK_OVERLAP_PDF', 150)
CHUNK_SIZE_TEXT = env('CHUNK_SIZE_TEXT', 1200)
DOCX_PARAS_PER_SEGMENT = env('DOCX_PARAS_PER_SEGMENT', 8)
TABLE_ROWS_PER_SEGMENT = env('TABLE_ROWS_PER_SEGMENT', 25)
OCR_MIN_CHARS_PER_PAGE = env('OCR_MIN_CHARS_PER_PAGE', 50)
OCR_DPI = env('OCR_DPI', 300)
CONF_HIGH = env('CONF_HIGH', 0.55)
CONF_MEDIUM = env('CONF_MEDIUM', 0.35)
LLM_PROVIDER = env('LLM_PROVIDER', 'ollama')
OLLAMA_URL = env('OLLAMA_URL', 'http://localhost:11434').rstrip('/')
LLM_MODEL = env('LLM_MODEL', 'qwen2.5:14b-instruct')
LLM_NUM_CTX = env('LLM_NUM_CTX', 8192)
LLM_TEMPERATURE = env('LLM_TEMPERATURE', 0.1)
LLM_KEEP_ALIVE = env('LLM_KEEP_ALIVE', '30m')
LLM_MAX_NEW_TOKENS = env('LLM_MAX_NEW_TOKENS', 1024)
API_RETRIES = env('API_RETRIES', 3)
API_BACKOFF_BASE_S = env('API_BACKOFF_BASE_S', 1.5)
SIM_W_TOPIC = env('SIM_W_TOPIC', 0.8)
SIM_W_DOCS = env('SIM_W_DOCS', 0.2)
SIM_THRESHOLD = env('SIM_THRESHOLD', 0.55)
DUPLICATE_THRESHOLD = env('DUPLICATE_THRESHOLD', 0.90)
TOPIC_RECLUSTER_DELTA = env('TOPIC_RECLUSTER_DELTA', 5)
ALLOW_ONLINE_LOOKUPS = env('ALLOW_ONLINE_LOOKUPS', False)
SEMANTIC_SCHOLAR_KEY = env('SEMANTIC_SCHOLAR_KEY', None)
YOUTUBE_API_KEY = env('YOUTUBE_API_KEY', None)
GITHUB_TOKEN = env('GITHUB_TOKEN', None)
CONTACT_EMAIL = env('CONTACT_EMAIL', None)
HOST = env('HOST', '127.0.0.1')
PORT = env('PORT', 8000)
CORS_ORIGINS = env('CORS_ORIGINS', ['http://localhost:5173', 'http://127.0.0.1:5173'])
DATA_DIR = Path(env('DATA_DIR', './data'))
DEVICE = env('DEVICE', 'auto')
MAX_UPLOAD_BYTES = env('MAX_UPLOAD_BYTES', 200 * 1024 * 1024)
OPENALEX_API_KEY = env('OPENALEX_API_KEY', None)
CONFLICT_PERCENT_TOLERANCE = env('CONFLICT_PERCENT_TOLERANCE', 1.0)
CONFLICT_RAW_RELATIVE_TOLERANCE = env('CONFLICT_RAW_RELATIVE_TOLERANCE', 0.02)
NLI_MODEL = env('NLI_MODEL', 'cross-encoder/nli-deberta-v3-small')
FAITHFULNESS_SSE_WAIT_S = env('FAITHFULNESS_SSE_WAIT_S', 3.0)
SIMILARITY_SHINGLE_SIZE = env('SIMILARITY_SHINGLE_SIZE', 8)
SIMILARITY_EXACT_THRESHOLD = env('SIMILARITY_EXACT_THRESHOLD', 0.60)
SIMILARITY_PARAPHRASE_THRESHOLD = env('SIMILARITY_PARAPHRASE_THRESHOLD', 0.85)
