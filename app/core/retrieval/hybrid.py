"""Pure ranking primitives; embeddings and indexes are separate future work."""
import config

def minmax(scores):
    if not scores: return {}
    low, high = min(scores.values()), max(scores.values())
    if high == low:
        return {key: float(value > 0) for key,value in scores.items()}
    return {key:(value-low)/(high-low) for key,value in scores.items()}

def merge_scores(semantic, bm25, semantic_weight=None, bm25_weight=None):
    """Merge candidate maps; missing scores are zero as specified for union."""
    keys = set(semantic) | set(bm25)
    sem = minmax(semantic)
    lexical = minmax(bm25)
    sw = config.HYBRID_W_SEMANTIC if semantic_weight is None else semantic_weight
    bw = config.HYBRID_W_BM25 if bm25_weight is None else bm25_weight
    return sorted(((k, sw*sem.get(k,0.0) + bw*lexical.get(k,0.0)) for k in keys), key=lambda x:(-x[1],x[0]))
