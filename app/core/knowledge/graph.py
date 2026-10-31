"""Graph storage, normalization and provenance; all writes remain in SQLite."""
import json,re,uuid
from app.db.session import connect

ALIASES={'bert base':'bert','bertbase':'bert','bert':'bert'}
def normalize(value):
    value=' '.join(re.findall(r'[a-z0-9]+',(value or '').lower()))
    return ALIASES.get(value,value)
def stable(*parts):return str(uuid.uuid5(uuid.NAMESPACE_URL,'paperwise:'+':'.join(parts)))

def node(db,typ,label,doc_id,unique=None):
    norm=normalize(label)
    if not norm:return None
    nid=stable('node',typ,unique or norm)
    db.execute('INSERT OR IGNORE INTO graph_nodes(id,type,label,norm_label) VALUES (?,?,?,?)',(nid,typ,label,norm))
    db.execute('INSERT OR IGNORE INTO graph_node_docs(node_id,doc_id) VALUES (?,?)',(nid,doc_id))
    return nid

def edge(db,source,target,typ,chunk_ids):
    if not source or not target or not chunk_ids:return
    eid=stable('edge',source,typ,target)
    previous=db.execute('SELECT chunk_ids_json FROM graph_edges WHERE id=?',(eid,)).fetchone()
    ids=sorted(set(json.loads(previous[0]) if previous else [])|set(chunk_ids))
    db.execute('INSERT INTO graph_edges(id,source_id,target_id,type,chunk_ids_json) VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET chunk_ids_json=excluded.chunk_ids_json',(eid,source,target,typ,json.dumps(ids)))

def remove_contributions(db,doc_id):
    ids={r[0] for r in db.execute('SELECT id FROM chunks WHERE doc_id=?',(doc_id,))}
    for r in db.execute('SELECT id,chunk_ids_json FROM graph_edges').fetchall():
        remain=[i for i in json.loads(r['chunk_ids_json']) if i not in ids]
        if remain:db.execute('UPDATE graph_edges SET chunk_ids_json=? WHERE id=?',(json.dumps(remain),r['id']))
        else:db.execute('DELETE FROM graph_edges WHERE id=?',(r['id'],))
    db.execute('DELETE FROM graph_node_docs WHERE doc_id=?',(doc_id,))
    db.execute('DELETE FROM graph_nodes WHERE NOT EXISTS (SELECT 1 FROM graph_node_docs gd WHERE gd.node_id=graph_nodes.id)')
    db.execute('DELETE FROM claims WHERE doc_id=?',(doc_id,))

def get_graph(doc_ids=None,node_types=None):
    with connect() as db:
        nodes=[]; valid=set()
        for row in db.execute('SELECT * FROM graph_nodes ORDER BY label').fetchall():
            docs=[r[0] for r in db.execute('SELECT doc_id FROM graph_node_docs WHERE node_id=? ORDER BY doc_id',(row['id'],))]
            if doc_ids and not set(docs)&set(doc_ids):continue
            if node_types and row['type'] not in node_types:continue
            valid.add(row['id']);nodes.append({'id':row['id'],'type':row['type'],'label':row['label'],'doc_ids':docs})
        edges=[]
        for row in db.execute('SELECT * FROM graph_edges ORDER BY id').fetchall():
            if row['source_id'] not in valid or row['target_id'] not in valid:continue
            chunks=json.loads(row['chunk_ids_json'])
            if doc_ids and chunks:
                marks=','.join('?' for _ in chunks)
                chunks=[r[0] for r in db.execute(f'SELECT id FROM chunks WHERE id IN ({marks}) AND doc_id IN ('+','.join('?' for _ in doc_ids)+')',chunks+doc_ids)]
                if not chunks:continue
            edges.append({'id':row['id'],'source':row['source_id'],'target':row['target_id'],'type':row['type'],'chunk_ids':chunks})
        return {'nodes':nodes,'edges':edges}

def citation(db,chunk_id):
    r=db.execute('SELECT c.*,d.title,d.filename FROM chunks c JOIN documents d ON d.id=c.doc_id WHERE c.id=?',(chunk_id,)).fetchone()
    if not r:return None
    return {'chunk_id':r['id'],'doc_id':r['doc_id'],'doc_title':r['title'] or r['filename'],
            'location_label':r['location_label'],'page':r['page'],'bboxes':json.loads(r['bboxes_json']) if r['bboxes_json'] else None,'snippet':r['text'][:300]}

def node_detail(node_id):
    graph=get_graph(); node_data=next((n for n in graph['nodes'] if n['id']==node_id),None)
    if not node_data:
        from app.errors import PaperWiseError
        raise PaperWiseError('NOT_FOUND','Graph node not found.',404)
    edges=[e for e in graph['edges'] if e['source']==node_id or e['target']==node_id]
    others={e['target'] if e['source']==node_id else e['source'] for e in edges}
    neighbors=[n for n in graph['nodes'] if n['id'] in others]
    with connect() as db:passages=[c for cid in dict.fromkeys(cid for e in edges for cid in e['chunk_ids']) if (c:=citation(db,cid))]
    return {'node':node_data,'neighbors':neighbors,'passages':passages}
