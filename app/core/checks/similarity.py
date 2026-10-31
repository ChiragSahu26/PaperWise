"""Offline exact-shingle and sentence-vector comparisons against uploaded papers."""
import json,re
from collections import defaultdict,Counter
import numpy as np
import config
from app.db.session import connect
from app.core.knowledge.graph import citation
from app.core.retrieval.embed import embed
from app.core.checks.faithfulness import sentence_spans

WORDS=re.compile(r"\b\w+(?:['’-]\w+)*\b",re.UNICODE)
def shingles(text):
    words=[x.lower() for x in WORDS.findall(text)];n=config.SIMILARITY_SHINGLE_SIZE
    return set(tuple(words[i:i+n]) for i in range(len(words)-n+1))

def target_spans(text,exclude_quotes):
    masked=text
    if exclude_quotes:
        chars=list(text)
        for match in re.finditer(r'"[^"\n]*"|“[^”]*”',text):
            for i in range(match.start(),match.end()):
                if chars[i]!='\n':chars[i]=' '
        masked=''.join(chars)
    offset=0
    for line in masked.splitlines(keepends=True):
        body=line.rstrip('\r\n');trimmed=body.strip();base=offset+len(body)-len(body.lstrip())
        for m in re.finditer(r'\S(?:.*?\S)?(?:(?<=[.!?])(?=\s+(?:[A-Z0-9]|$))|$)',trimmed):
            start,end=base+m.start(),base+m.end();sent=text[start:end]
            if exclude_quotes and re.match(r'^\s*(?:\[\d+\]|\([^)]*\d{4}[^)]*\)|\w+\s+et\s+al\.)',sent,re.I):continue
            yield start,end,sent
        offset+=len(line)

def document_text(rows):
    # Overlapping chunks from the same original segment are stitched by character offsets.
    parts=[];segment=None;used=0
    for r in rows:
        if r['type']=='metadata':continue
        if r['segment_index']!=segment:
            if parts:parts.append('\n\n')
            segment=r['segment_index'];used=0
        start=r['char_start'] or 0;value=r['text'];skip=max(0,used-start)
        if skip<len(value):parts.append(value[skip:])
        used=max(used,r['char_end'] or (start+len(value)))
    return ''.join(parts)

def run_check(report_id,payload):
    with connect() as db:
        source=[dict(r) for r in db.execute("SELECT c.* FROM chunks c JOIN documents d ON d.id=c.doc_id WHERE d.status='ready' AND c.type!='metadata' AND (? IS NULL OR c.doc_id!=?) ORDER BY c.doc_id,c.segment_index,c.char_start",(payload.get('doc_id'),payload.get('doc_id')))]
        if payload.get('text') is None:
            target=[dict(r) for r in db.execute("SELECT * FROM chunks WHERE doc_id=? ORDER BY segment_index,char_start",(payload['doc_id'],))]
            text=document_text(target)
        else:text=payload['text']
    all_targets=list(target_spans(text,payload['exclude_quotes']))
    total_words=sum(len(WORDS.findall(s)) for _,_,s in all_targets)
    targets=[(a,b,s) for a,b,s in all_targets if len(WORDS.findall(s))>=config.SIMILARITY_SHINGLE_SIZE]
    index=defaultdict(lambda:defaultdict(set))
    sources=[]
    for c in source:
        idx=len(sources);sources.append((c['text'],c))
        for shingle in shingles(c['text']):index[shingle][c['doc_id']].add(idx)
    # Paraphrase comparisons use sentences, not whole chunks.
    sentence_sources=[(s,c) for c in source for _,_,s in sentence_spans(c['text']) if len(WORDS.findall(s))>=config.SIMILARITY_SHINGLE_SIZE]
    exact={};unmatched=[]
    for pos,(a,b,s) in enumerate(targets):
        grams=shingles(s);counts=Counter();locations=defaultdict(Counter)
        for gram in grams:
            for doc,indices in index.get(gram,{}).items():
                counts[doc]+=1
                for i in indices:locations[doc][i]+=1
        if grams and counts:
            doc,count=counts.most_common(1)[0];score=count/len(grams)
            if score>=config.SIMILARITY_EXACT_THRESHOLD:
                index_best=locations[doc].most_common(1)[0][0];exact[pos]=(sources[index_best][1],score,'exact');continue
        unmatched.append(pos)
    if unmatched and sentence_sources:
        target_vectors=np.asarray(embed([targets[i][2] for i in unmatched]))
        source_vectors=np.asarray(embed([s for s,_ in sentence_sources]))
        for i,vec in zip(unmatched,target_vectors):
            sims=source_vectors@vec;j=int(np.argmax(sims));score=float(sims[j])
            if score>=config.SIMILARITY_PARAPHRASE_THRESHOLD:exact[i]=(sentence_sources[j][1],score,'paraphrase')
    with connect() as db:
        matches=[]
        for i,(a,b,s) in enumerate(targets):
            if i in exact:
                chunk,score,typ=exact[i];ref=citation(db,chunk['id'])
                matches.append({'source_doc_id':chunk['doc_id'],'source_citation':ref,'text_span':{'start':a,'end':b},'text':s,'kind':typ,'similarity':round(score,4)})
        matched_words=sum(len(WORDS.findall(m['text'])) for m in matches)
        report={'overall_percent':round(100*matched_words/total_words,2) if total_words else 0.0,'matches':matches}
        db.execute('UPDATE similarity_checks SET result_json=? WHERE id=?',(json.dumps(report),report_id))
    return report
