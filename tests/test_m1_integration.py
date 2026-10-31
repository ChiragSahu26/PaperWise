import io, time
import pytest
from fastapi.testclient import TestClient
from docx import Document
from pptx import Presentation
from openpyxl import Workbook
import config
from app.main import app
from app.core.retrieval.search import retrieve
from app.errors import PaperWiseError

@pytest.mark.usefixtures("embedding_model_cached")
def test_real_upload_all_formats_and_active_document_filter(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA_DIR',tmp_path)
    monkeypatch.setattr(config,'OLLAMA_URL','http://127.0.0.1:1')
    doc=Document();doc.add_paragraph('Orchid experiment achieved 95 percent accuracy.');d=io.BytesIO();doc.save(d)
    ppt=Presentation();slide=ppt.slides.add_slide(ppt.slide_layouts[1]);slide.shapes.title.text='Orchid experiment results';p=io.BytesIO();ppt.save(p)
    wb=Workbook();wb.active.append(['plant','result']);wb.active.append(['orchid','95 percent']);x=io.BytesIO();wb.save(x)
    from pathlib import Path
    pdf=Path('tests/fixtures/two_column.pdf').read_bytes()
    files=[('files',('p.pdf',pdf,'application/pdf')),('files',('w.docx',d.getvalue(),'application/octet-stream')),
           ('files',('s.pptx',p.getvalue(),'application/octet-stream')),('files',('t.txt',b'Orchid experiment achieved accuracy of 95 percent.','text/plain')),
           ('files',('m.md',b'# Methods\nOrchid experiment methods were successful.','text/plain')),
           ('files',('c.csv',b'plant,result\norchid,95 percent\n','text/csv')),
           ('files',('x.xlsx',x.getvalue(),'application/octet-stream'))]
    with TestClient(app) as client:
        res=client.post('/api/v1/documents',files=files);assert res.status_code==200,res.text
        ids=[x['doc_id'] for x in res.json()]
        for _ in range(500):
            docs=client.get('/api/v1/documents').json()
            if all(d['status'] in ('ready','failed') for d in docs): break
            time.sleep(.05)
        assert len(docs)==7 and all(d['status']=='ready' for d in docs),docs
        found=retrieve('What was the orchid accuracy?',[ids[3]],top_k=3,mode='hybrid')
        assert found['retrieved'] and all(c['chunk']['doc_id']==ids[3] for c in found['retrieved'])
        assert any('95 percent' in c['chunk']['text'] for c in found['retrieved'])
        with pytest.raises(PaperWiseError) as exc: retrieve('question',[])
        assert exc.value.code=='NO_DOCUMENTS_SELECTED'
        assert client.delete('/api/v1/documents/'+ids[3]).status_code==200
        with pytest.raises(PaperWiseError) as exc: retrieve('question',[ids[3]])
        assert exc.value.code=='NOT_FOUND'
