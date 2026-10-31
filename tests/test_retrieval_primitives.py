import pytest
from app.core.retrieval.expand import expand_query
from app.core.retrieval.confidence import evidence_match
from app.core.retrieval.hybrid import minmax, merge_scores
from app.core.retrieval.bm25 import tokenize

def test_query_expansion():
    assert expand_query('  results?  ') == 'results results performance accuracy evaluation metrics experiments comparison'
    assert expand_query('what are the results today?') == 'what are the results today'
    assert expand_query('unknown?') == 'unknown'
    assert 'dataset data corpus' in expand_query('Results and dataset')

def test_normalization_and_union():
    assert minmax({}) == {}
    assert minmax({'a':1,'b':1}) == {'a':1.,'b':1.}
    assert minmax({'a':0,'b':0}) == {'a':0.,'b':0.}
    assert merge_scores({'a':1.0},{'b':1.0}) == [('a',0.65),('b',0.35)]
    assert merge_scores({'a':1.0},{'a':1.0}) == [('a',1.0)]

def test_confidence():
    assert evidence_match([.55])['level'] == 'high'
    assert evidence_match([.35])['level'] == 'medium'
    assert evidence_match([]) == {'level':'low','score':0}

def test_bm25_tokenization():
    assert tokenize('The BERT-base and GPT-4: model_v2.1',query=True) == ['bert-base','gpt-4','model_v2.1']
    assert tokenize('The test') == ['the','test']

def test_absent_method_is_zero_after_normalization():
    # A missing score must not outrank negative semantic scores after scaling.
    result=dict(merge_scores({'a':-.4, 'b':-.2},{'c':1.0}))
    assert result['a'] == 0 and result['b'] == 0.65 and result['c'] == 0.35
