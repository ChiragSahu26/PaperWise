"""Run retrieval evaluation offline over pre-indexed IDs or bundled fixture IDs."""
import argparse, json, shutil, sys, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import config
from app.db.session import initialize,connect
from app.jobs.ingest import ingest_document
from app.jobs.queue import now
from app.core.retrieval.search import retrieve

def seed_fixture(doc_id):
    fixture={'fixture_1':'eval_paper_1.txt','fixture_2':'eval_paper_2.txt'}.get(doc_id)
    if not fixture: return
    with connect() as db:
        if db.execute('SELECT 1 FROM documents WHERE id=?',(doc_id,)).fetchone(): return
    folder=config.DATA_DIR/'uploads'/doc_id; folder.mkdir(parents=True,exist_ok=True)
    target=folder/fixture; shutil.copyfile(ROOT/'tests'/'fixtures'/fixture,target)
    job=str(uuid.uuid4()); stamp=now()
    with connect() as db:
        db.execute('INSERT INTO documents(id,filename,file_path,file_type,status,added_at) VALUES (?,?,?,?,?,?)',(doc_id,fixture,str(target.resolve()),'txt','queued',stamp))
        db.execute("INSERT INTO jobs(id,kind,status,created_at,updated_at) VALUES (?,?,?, ?,?)",(job,'ingest','running',stamp,stamp))
    ingest_document(doc_id,job,lambda event:None)

def relevant_total(doc_ids,gold):
    placeholders=','.join('?' for _ in doc_ids)
    with connect() as db: chunks=db.execute(f'SELECT id,text FROM chunks WHERE doc_id IN ({placeholders})',doc_ids).fetchall()
    return {c['id'] for c in chunks if any(s.lower() in c['text'].lower() for s in gold)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compare-modes',action='store_true')
    parser.add_argument('--answers',action='store_true',help='Run real-model answer-quality evaluation via API')
    parser.add_argument('--models',default='',help='Comma-separated Ollama model names for --answers')
    parser.add_argument('--api-url',default='http://127.0.0.1:8000/api/v1')
    parser.add_argument('--faithfulness-timeout',type=float,default=120)
    parser.add_argument('--questions',default='tests/eval/questions.json')
    parser.add_argument('--k',type=int,default=5)
    args=parser.parse_args()
    if not 1<=args.k<=20: parser.error('--k must be in 1..20')
    if args.answers:
        if not args.models: parser.error('--answers requires --models')
        from run_answer_evaluation import run
        return run(args)
    data=json.loads(Path(args.questions).read_text())
    if not data: parser.error('Question list is empty')
    initialize()
    for doc_id in {d for q in data for d in q['doc_ids']}: seed_fixture(doc_id)
    modes=['semantic','bm25','hybrid','hybrid_rerank'] if args.compare_modes else ['hybrid_rerank']
    results=[]
    for mode in modes:
        p=r=h=0.0
        for q in data:
            relevant=relevant_total(q['doc_ids'],q['gold_snippets'])
            if not relevant: raise ValueError(f"No gold chunk found for question: {q['question']}")
            found=retrieve(q['question'],q['doc_ids'],args.k,mode)['retrieved']
            count=len({item['chunk']['id'] for item in found}&relevant)
            p+=count/args.k; r+=count/len(relevant); h+=float(count>0)
        n=len(data)
        results.append({'mode':mode,'precision_at_k':p/n,'recall_at_k':r/n,'hit_at_k':h/n})
    lines=['| Mode | Precision@K | Recall@K | Hit@K |','|---|---:|---:|---:|']
    lines += [f"| {x['mode']} | {x['precision_at_k']:.3f} | {x['recall_at_k']:.3f} | {x['hit_at_k']:.3f} |" for x in results]
    table='\n'.join(lines)+'\n';print(table)
    Path('eval_results.json').write_text(json.dumps({'k':args.k,'questions':len(data),'results':results},indent=2)+'\n')
    Path('eval_results.md').write_text(table)

if __name__=='__main__': main()
