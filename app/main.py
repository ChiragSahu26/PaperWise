from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import config
from app.db.session import initialize
from app.errors import register_handlers
from app.api import health, settings, documents, chats, chat_extras, intelligence, notes, knowledge, similarity
from app.core.generation.ollama_provider import OllamaProvider
import asyncio
from app.jobs.queue import JobQueue

@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    # Best effort only: an unavailable Ollama is not a startup failure.
    await health.ollama_tags()
    app.state.generations = {}
    app.state.llm_lock = asyncio.Lock()
    app.state.interactive_waiters = 0
    if not hasattr(app.state, "llm_provider"):
        app.state.llm_provider = OllamaProvider()
    app.state.jobs = JobQueue(app)
    await app.state.jobs.start()
    try:
        yield
    finally:
        await app.state.jobs.close()

app = FastAPI(title='PaperWise Backend', version='0.1.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=['*'], allow_headers=['*'])
register_handlers(app)
app.include_router(health.router, prefix='/api/v1', tags=['health'])
app.include_router(settings.router, prefix='/api/v1', tags=['settings'])
app.include_router(documents.router, prefix='/api/v1', tags=['documents'])

app.include_router(chats.router, prefix='/api/v1', tags=['chats'])

app.include_router(chat_extras.router, prefix='/api/v1', tags=['chat extras'])

app.include_router(intelligence.router, prefix='/api/v1', tags=['paper intelligence'])

app.include_router(notes.router, prefix='/api/v1', tags=['notes'])

app.include_router(knowledge.router, prefix='/api/v1', tags=['knowledge'])

app.include_router(similarity.router, prefix='/api/v1', tags=['similarity checks'])
