#!/usr/bin/env python3
"""Unmocked end-to-end check. Start PaperWise and Ollama with local model weights first."""
import argparse,json,sys
from pathlib import Path
from api_stream import PaperWiseClient

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--api-url',default='http://127.0.0.1:8000/api/v1')
    p.add_argument('--model',default=None,help='Installed Ollama model (default: API setting)')
    args=p.parse_args();client=PaperWiseClient(args.api_url)
    fixture=Path(__file__).resolve().parents[1]/'tests/fixtures/eval_paper_1.txt'
    checks=[('answerable','What was the crop classifier accuracy?',False),('unanswerable','What is the secret password of the researchers?',True)]
    failed=0
    try:
        doc=client.upload(fixture);print('Uploaded fixture paper:',doc)
        for name,question,should_refuse in checks:
            print(f'\n{name}: {question}\nAnswer: ',end='',flush=True)
            try:
                result=client.ask([doc],question,args.model,print_stream=True)
                print('Citations:',json.dumps(result['citations'],ensure_ascii=False))
                print('Refused:',result['refused'],'TTFT (s):',result['ttft_s'],'tokens/s:',result['tokens_per_s'])
                valid=(result['refused']==should_refuse)
                if not should_refuse:valid=valid and '93' in result['answer'] and any(c.get('cited') for c in result['citations'])
                else:valid=valid and result['answer'].startswith('I could not find this in the selected documents.')
                print('PASS' if valid else 'FAIL');failed+=not valid
            except Exception as exc:
                print('\nFAIL:',type(exc).__name__,str(exc));failed+=1
    finally:client.close()
    return 1 if failed else 0
if __name__=='__main__':sys.exit(main())
