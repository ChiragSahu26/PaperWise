"""Answer-quality evaluation over real HTTP, real Ollama and local judges."""
import json,statistics
from pathlib import Path
from api_stream import PaperWiseClient
UNANSWERABLE=[
 'What is the secret password of the research team?',
 'What is the atomic mass of an invented element called floranium?',
 'What year was the first human settlement established on Mars?',
 'Which restaurant did the authors visit after the experiment?',
 'What is the telephone number of the lead author?',
 'What was the exact weather at the laboratory on 3 January 1982?',
 'What is the name of the authors’ family pet?',
 'How many Jupiter moons are made of chocolate?',
 'What is the private bank account number of the authors?',
 'What score did the model achieve on a benchmark called Unobtainium-999?',
]
def run(args):
    base=Path(__file__).resolve().parents[1];data=json.loads(Path(args.questions).read_text())
    models=[m.strip() for m in args.models.split(',') if m.strip()]
    if not models:raise ValueError('--models must contain at least one installed Ollama model')
    client=PaperWiseClient(args.api_url);results=[]
    try:
        docmap={name:client.upload(base/'tests/fixtures'/filename) for name,filename in [('fixture_1','eval_paper_1.txt'),('fixture_2','eval_paper_2.txt')]}
        for model in models:
            answers=[];refusals=0;ttft=[];rates=[];supported=total=0;missing=0
            for q in data+[{ 'question':x,'doc_ids':['fixture_1'],'unanswerable':True } for x in UNANSWERABLE]:
                docs=[docmap.get(x,x) for x in q['doc_ids']]
                try:
                    result=client.ask(docs,q['question'],model)
                    if q.get('unanswerable'):refusals+=bool(result['refused'])
                    if result['ttft_s'] is not None:ttft.append(result['ttft_s'])
                    if result['tokens_per_s'] is not None:rates.append(result['tokens_per_s'])
                    if not result['refused']:
                        faith=client.await_faithfulness(result,timeout=args.faithfulness_timeout)
                        if faith is None:missing+=1
                        else:
                            total+=len(faith);supported+=sum(s['label']=='supported' for s in faith)
                    answers.append({'question':q['question'],**result})
                except Exception as exc:
                    missing+=1;answers.append({'question':q['question'],'error':str(exc)})
                print(model, q['question'], 'refused:',answers[-1].get('refused','ERROR'),flush=True)
            results.append({'model':model,'refusal_accuracy':refusals/len(UNANSWERABLE),'faithfulness':supported/total if total else None,
                            'faithfulness_sentences':total,'missing_judgments_or_errors':missing,
                            'mean_ttft_s':statistics.mean(ttft) if ttft else None,'mean_tokens_per_s':statistics.mean(rates) if rates else None,'answers':answers})
    finally:client.close()
    output={'mode':'answers','note':'Tokens/sec uses the Ollama stream token-event count; missing judgments are excluded from faithfulness.','results':results}
    Path('answer_eval_results.json').write_text(json.dumps(output,indent=2,ensure_ascii=False)+'\n')
    lines=['| Model | Refusal accuracy | Faithfulness | Mean TTFT (s) | Mean tokens/s | Missing judgments/errors |','|---|---:|---:|---:|---:|---:|']
    def fmt(x):return 'N/A' if x is None else f'{x:.3f}'
    lines.extend(f"| {r['model']} | {fmt(r['refusal_accuracy'])} | {fmt(r['faithfulness'])} | {fmt(r['mean_ttft_s'])} | {fmt(r['mean_tokens_per_s'])} | {r['missing_judgments_or_errors']} |" for r in results)
    Path('answer_eval_results.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines))
