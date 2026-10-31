import config

def evidence_match(cosines):
    """Mean cosine of the available final chunks. Empty evidence is low/zero."""
    values = list(cosines)
    score = sum(values) / len(values) if values else 0.0
    level = 'high' if score >= config.CONF_HIGH else 'medium' if score >= config.CONF_MEDIUM else 'low'
    return {'level':level, 'score':score}
