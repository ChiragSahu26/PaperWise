import pytest
import math
from app.core.ingestion.types import Chunk
from app.core.retrieval import vector_store
import config

@pytest.mark.usefixtures("embedding_model_cached")
def test_real_embeddings_and_chroma(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    def make(doc,text): return Chunk(doc+':0:0',doc,0,0,text,'Part 1',None,0,len(text),None)
    vector_store.replace_document('a',[make('a','Machine learning on medical images')])
    vector_store.replace_document('b',[make('b','Gardening with flowers')])
    v=vector_store.embed(['medical imaging'])[0]
    assert len(v)==384 and math.isclose(sum(x*x for x in v),1.0,abs_tol=1e-5)
    result=vector_store.semantic_search(['a'],v,50)
    assert len(result)==1 and result[0][0]=='a:0:0'
    vector_store.delete_document('a')
    assert vector_store.semantic_search(['a'],v,50)==[]
