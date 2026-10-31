"""Script plumbing tests with fake HTTP/client responses; not real-model checks."""
import importlib.util,json,sys
from pathlib import Path
from types import SimpleNamespace
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from api_stream import PaperWiseClient
import run_answer_evaluation

def test_sse_parser_with_mock_transport():
    c=PaperWiseClient('http://local/api/v1')
    stream='event: citations\ndata: []\n\nevent: token\ndata: {"text":"answer [1]"}\n\nevent: done\ndata: {"message_id":"m","refused":false,"tokens":3}\n\n'
    def respond(request):
        path=request.url.path
        if path.endswith('/chats'):return httpx.Response(200,json={'id':'chat'})
        if request.method=='POST':return httpx.Response(200,text=stream)
        return httpx.Response(200,json={'citations':[{'cited':True}], 'faithfulness':[{'label':'supported'}]})
    c.client.close();c.client=httpx.Client(base_url='http://local/api/v1/',transport=httpx.MockTransport(respond))
    result=c.ask(['doc'],'Q','model');c.close()
    assert result['answer']=='answer [1]' and not result['refused'] and result['tokens']==3
    assert result['ttft_s'] is not None and result['tokens_per_s'] is not None

def test_answer_evaluation_metrics_with_scripted_client(tmp_path,monkeypatch):
    questions=tmp_path/'questions.json';questions.write_text(json.dumps([{'question':'Q','doc_ids':['fixture_1']}]))
    class MockClient:
        def __init__(self,url):self.count=0
        def upload(self,path):return Path(path).name
        def close(self):pass
        def ask(self,docs,question,model):
            self.count+=1
            return {'refused':self.count>1,'ttft_s':1.,'tokens_per_s':2.,'faithfulness':[{'label':'supported'}]}
        def await_faithfulness(self,result,timeout):return result['faithfulness']
    monkeypatch.setattr(run_answer_evaluation,'PaperWiseClient',MockClient);monkeypatch.chdir(tmp_path)
    run_answer_evaluation.run(SimpleNamespace(questions=str(questions),models='local-model',api_url='http://example.invalid',faithfulness_timeout=0))
    result=json.loads((tmp_path/'answer_eval_results.json').read_text())['results'][0]
    assert result['refusal_accuracy']==1.0 and result['faithfulness']==1.0 and len(result['answers'])==11
