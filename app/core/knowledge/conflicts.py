from app.db.session import connect
import json
from collections import defaultdict
from app.core.knowledge.graph import normalize,stable,citation
from app.jobs.queue import now
import config
NOTE='These papers report different values. They may differ because of different splits, settings or definitions; check the experimental setup.'

def recompute(db):
    grouped=defaultdict(list)
    for r in db.execute('SELECT * FROM claims WHERE dataset IS NOT NULL AND metric IS NOT NULL AND value IS NOT NULL AND chunk_id IS NOT NULL').fetchall():
        grouped[(normalize(r['dataset']),normalize(r['metric']),normalize(r['setting']),r['unit'] or 'raw')].append(r)
    db.execute('DELETE FROM conflicts')
    for key,rows in grouped.items():
        if len({r['doc_id'] for r in rows})<2:continue
        values=[r['value'] for r in rows];spread=max(values)-min(values)
        threshold=config.CONFLICT_PERCENT_TOLERANCE if key[3]=='percent' else config.CONFLICT_RAW_RELATIVE_TOLERANCE*max(abs(max(values)),abs(min(values)))
        if spread<=threshold:continue
        entries=[]
        for r in rows:
            source=citation(db,r['chunk_id'])
            if source:entries.append({'doc_id':r['doc_id'],'value':r['value'],'citation':source})
        if len({e['doc_id'] for e in entries})<2:continue
        db.execute('INSERT INTO conflicts(id,dataset,metric,setting,entries_json,note,created_at) VALUES (?,?,?,?,?,?,?)',
                   (stable('conflict',*key),rows[0]['dataset'],rows[0]['metric'],rows[0]['setting'],json.dumps(entries),NOTE,now()))

def list_conflicts(doc_ids=None):
    with connect() as db:rows=db.execute('SELECT * FROM conflicts ORDER BY created_at,id').fetchall()
    results=[]
    for row in rows:
        entries=json.loads(row['entries_json'])
        if doc_ids:entries=[e for e in entries if e['doc_id'] in doc_ids]
        if len({e['doc_id'] for e in entries})<2:continue
        if doc_ids:
            with connect() as db:
                unit=db.execute('SELECT unit FROM claims WHERE chunk_id=? AND dataset=? AND metric=? LIMIT 1',(entries[0]['citation']['chunk_id'],row['dataset'],row['metric'])).fetchone()
            values=[e['value'] for e in entries];spread=max(values)-min(values)
            threshold=config.CONFLICT_PERCENT_TOLERANCE if unit and unit['unit']=='percent' else config.CONFLICT_RAW_RELATIVE_TOLERANCE*max(abs(max(values)),abs(min(values)))
            if spread<=threshold:continue
        results.append({'id':row['id'],'dataset':row['dataset'],'metric':row['metric'],'setting':row['setting'],'entries':entries,'note':row['note']})
    return results
