import json,time
from pathlib import Path
import pytest, fitz
from PIL import Image
from fastapi.testclient import TestClient
import config
from app.main import app
from scripts.render_highlights import render

class LLM:
    async def stream(self,messages,**kwargs): yield 'The title is given on the first page [1].'

@pytest.mark.usefixtures('embedding_model_cached')
def test_pdf_citations_boxes_overlap_rendered_text_and_range(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path/'data');monkeypatch.setattr(config,'OLLAMA_URL','http://127.0.0.1:1')
    app.state.llm_provider=LLM(); path=Path('tests/fixtures/two_column.pdf'); original=path.read_bytes()
    with TestClient(app) as client:
        client.put('/api/v1/settings',json={'use_reranker':False})
        docid=client.post('/api/v1/documents',files={'files':('paper.pdf',original,'application/pdf')}).json()[0]['doc_id']
        for _ in range(300):
            status=client.get('/api/v1/documents/'+docid).json()['status']
            if status in ('ready','failed'):break
            time.sleep(.05)
        assert status=='ready'
        ranged=client.get('/api/v1/documents/'+docid+'/file',headers={'Range':'bytes=10-99'})
        assert ranged.status_code==206 and ranged.content==original[10:100] and ranged.headers['content-range'].startswith('bytes 10-99/')
        chat=client.post('/api/v1/chats',json={'doc_ids':[docid]}).json()['id']
        response=client.post(f'/api/v1/chats/{chat}/messages',json={'question':'What is the title?'})
        blocks=response.text.split('\n\n');c=next(json.loads(b.splitlines()[1][6:]) for b in blocks if b.startswith('event: citations'))
        assert c
        with fitz.open(path) as pdf:
            for cit in c:
                assert cit['page'] and cit['bboxes'] and cit['doc_id']==docid
                words=pdf[cit['page']-1].get_text('words')
                assert any(fitz.Rect(box).intersects(fitz.Rect(w[:4])) for box in cit['bboxes'] for w in words)
                chunk=client.get(f"/api/v1/documents/{docid}/chunks/{cit['chunk_id']}").json()
                assert chunk['page']==cit['page'] and chunk['bboxes']==cit['bboxes']
        output=tmp_path/'debug.png';render(path,c[0]['page'],c[0]['bboxes'],str(output))
        image=Image.open(output).convert('RGB')
        assert image.size[0]>0 and any(r>g*1.2 and r>b*1.2 for r,g,b in image.getdata())
