"""Deterministic query expansion; no model call."""
import re

EXPANSIONS = {
    ('results','result','performance'): 'results performance accuracy evaluation metrics experiments comparison',
    ('dataset','data'): 'dataset data corpus benchmark training test split samples',
    ('method','approach','methodology'): 'method methodology approach proposed model architecture algorithm',
    ('limitations','weakness'): 'limitations limitation future work drawbacks challenges',
    ('contribution','contributions'): 'contributions contribution novel proposed we propose',
    ('conclusion',): 'conclusion conclusions summary discussion',
    ('author','authors'): 'authors author affiliation university',
    ('title',): 'title paper abstract',
}

def expand_query(question: str) -> str:
    query = re.sub(r'\s+', ' ', question.strip()).removesuffix('?').rstrip()
    if len(query.split()) > 4: return query
    tokens = set(re.findall(r'[a-z0-9]+(?:[-_.][a-z0-9]+)*', query.lower()))
    terms = [text for triggers,text in EXPANSIONS.items() if tokens.intersection(triggers)]
    return ' '.join([query, *terms]).strip()
