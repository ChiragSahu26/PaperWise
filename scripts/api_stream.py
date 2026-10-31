"""Real HTTP helpers for smoke tests and answer-quality evaluation (no mocks)."""
import json,time
from pathlib import Path
import httpx

class PaperWiseClient:
    def __init__(self,api_url,timeout=300):
        self.client=httpx.Client(base_url=api_url.rstrip('/')+'/',timeout=timeout)
    def close(self):self.client.close()
    def request(self,method,path,**kwargs):
        response=self.client.request(method,path.lstrip('/'),**kwargs);response.raise_for_status();return response.json()
    def upload(self,path):
        path=Path(path)
        with path.open('rb') as f:result=self.request('POST','documents',files={'files':(path.name,f,'text/plain')})
        doc=result[0]['doc_id'];deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            status=self.request('GET','documents/'+doc)
            if status['status']=='ready':return doc
            if status['status']=='failed':raise RuntimeError('Ingestion failed: '+str(status.get('error')))
            time.sleep(.25)
        raise TimeoutError('Document ingestion did not finish')
    def ask(self,doc_ids,question,model=None,print_stream=False):
        chat=self.request('POST','chats',json={'doc_ids':doc_ids})['id'];body={'question':question}
        if model:body['model']=model
        started=time.monotonic();first=None;done_time=None;event=None;citations=[];answer=[];done=None;faith=None;errors=[]
        with self.client.stream('POST',f'chats/{chat}/messages',json=body) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith('event: '):event=line[7:]
                elif line.startswith('data: '):
                    data=json.loads(line[6:])
                    if event=='citations':citations=data
                    elif event=='token':
                        if first is None:first=time.monotonic()
                        answer.append(data['text'])
                        if print_stream:print(data['text'],end='',flush=True)
                    elif event=='done':done=data;done_time=time.monotonic()
                    elif event=='faithfulness':faith=data['sentences']
                    elif event=='error':errors.append(data)
        if print_stream:print()
        if not done:raise RuntimeError('No done event: '+json.dumps(errors))
        message=self.request('GET',f"chats/{chat}/messages/{done['message_id']}")
        return {'chat_id':chat,'message_id':done['message_id'],'answer':''.join(answer),'citations':message.get('citations',citations),
                'refused':done['refused'],'ttft_s':first-started if first else None,
                'tokens_per_s':done['tokens']/max(.001,done_time-first) if first else None,
                'faithfulness':message.get('faithfulness') if message.get('faithfulness') is not None else faith,'tokens':done['tokens']}
    def await_faithfulness(self,result,timeout=120):
        deadline=time.monotonic()+timeout
        while result['faithfulness'] is None and time.monotonic()<deadline:
            msg=self.request('GET',f"chats/{result['chat_id']}/messages/{result['message_id']}")
            result['faithfulness']=msg.get('faithfulness')
            if result['faithfulness'] is None:time.sleep(.5)
        return result['faithfulness']
