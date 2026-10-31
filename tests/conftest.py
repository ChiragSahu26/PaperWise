import pytest
import config

@pytest.fixture
def embedding_model_cached():
    """Never download model weights during tests; skip only the real-model tests."""
    from huggingface_hub import try_to_load_from_cache
    from pathlib import Path
    files=('config.json','tokenizer.json','1_Pooling/config.json')
    missing=[f for f in files if not isinstance(try_to_load_from_cache(config.EMBEDDING_MODEL,f),str)]
    weights=any(isinstance(try_to_load_from_cache(config.EMBEDDING_MODEL,f),str) for f in ('model.safetensors','pytorch_model.bin'))
    if missing or not weights:
        pytest.skip('Embedding model weights not in Hugging Face cache; provision all-MiniLM-L6-v2 to run real-model tests')

@pytest.fixture
def nli_model_cached():
    from huggingface_hub import try_to_load_from_cache
    files=('config.json','tokenizer.json')
    missing=[f for f in files if not isinstance(try_to_load_from_cache(config.NLI_MODEL,f),str)]
    weights=any(isinstance(try_to_load_from_cache(config.NLI_MODEL,f),str) for f in ('model.safetensors','pytorch_model.bin'))
    if missing or not weights:
        pytest.skip('NLI model weights not in Hugging Face cache; provision cross-encoder/nli-deberta-v3-small to run real-model tests')
