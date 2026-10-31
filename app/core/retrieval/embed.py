import logging, threading, time
import config
log=logging.getLogger(__name__)
_model=None
_model_lock=threading.Lock()
_encode_lock=threading.Lock()

def device():
    if config.DEVICE != 'auto': return config.DEVICE
    import torch
    return 'mps' if torch.backends.mps.is_available() else 'cpu'

def model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                start=time.monotonic()
                from sentence_transformers import SentenceTransformer
                # Models are provisioned separately; normal backend operation does not use the network.
                _model=SentenceTransformer(config.EMBEDDING_MODEL,device=device(),local_files_only=True)
                log.info('Loaded embedding model in %.2fs',time.monotonic()-start)
    return _model

def embed(texts):
    if not texts: return []
    with _encode_lock:
        return model().encode(texts,batch_size=64,normalize_embeddings=True,show_progress_bar=False).tolist()
