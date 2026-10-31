import logging, threading, time
import config
from .embed import device
log=logging.getLogger(__name__)
_model=None
_lock=threading.Lock()

def score(question, texts):
    global _model
    with _lock:
        if _model is None:
            start=time.monotonic()
            from sentence_transformers import CrossEncoder
            _model=CrossEncoder(config.RERANK_MODEL,device=device(),local_files_only=True)
            log.info('Loaded cross encoder in %.2fs',time.monotonic()-start)
        return [float(x) for x in _model.predict([(question,t) for t in texts],show_progress_bar=False)]
