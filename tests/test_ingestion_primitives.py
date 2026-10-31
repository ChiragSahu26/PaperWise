from pathlib import Path
from app.core.ingestion.columns import order_blocks
from app.core.ingestion.chunker import split_ranges, chunk_segment
from app.core.ingestion.types import Segment
from app.core.ingestion.readers import read_file

def test_column_separators():
    blocks=[(0,0,100,10,'title'),(3,20,40,25,'L1'),(60,21,97,26,'R1'),(3,30,40,35,'L2'),(60,31,97,36,'R2'),(0,50,100,60,'wide')]
    assert [b[4] for b in order_blocks(blocks,100)] == ['title','L1','L2','R1','R2','wide']

def test_chunk_ranges_and_boxes():
    text='abcd '*100
    ranges=list(split_ranges(text,100,15))
    assert ranges[0][0] == 0 and ranges[-1][1]==len(text)
    assert all(a[1]-b[0]==15 for a,b in zip(ranges,ranges[1:]))
    s=Segment('d',0,text,'Page 1',1,[(0,25,[1,2,3,4])])
    assert chunk_segment(s,'pdf')[0].bboxes == [[1,2,3,4]]

def test_text_csv_and_file_sniff(tmp_path):
    p=tmp_path/'doc.md'; p.write_text('# Intro\nHello world\n')
    segments,w=read_file(p,'d'); assert segments[0].location_label=='Section: Intro'
    p=tmp_path/'doc.csv'; p.write_text('Name,Score\n'+'A,3\n'*26)
    segments,w=read_file(p,'d'); assert len(segments)==2 and segments[1].text.startswith('Name | Score') and segments[1].location_label=='Rows 26-26'
    p=tmp_path/'bad.pdf'; p.write_text('not a pdf')
    import pytest
    with pytest.raises(ValueError,match='UNSUPPORTED_FILE'): read_file(p,'d')

def test_pdf_text_blocks(tmp_path):
    import fitz
    doc=fitz.open(); page=doc.new_page(width=400,height=600)
    page.insert_text((20,80),'Left one this is sufficiently long to avoid the OCR process.')
    path=tmp_path/'test.pdf';doc.save(path);doc.close()
    segments,w=read_file(path,'d')
    assert not w and segments[0].page == 1 and segments[0].spans

def test_docx_pptx_xlsx(tmp_path):
    from docx import Document
    from pptx import Presentation
    from openpyxl import Workbook
    doc=Document(); doc.add_heading('Methods',level=1);doc.add_paragraph('Research method')
    path=tmp_path/'doc.docx';doc.save(path)
    segments,_=read_file(path,'d'); assert any('Research method' in s.text and 'Methods' in s.location_label for s in segments)
    deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[1]);slide.shapes.title.text='A slide'
    path=tmp_path/'slides.pptx';deck.save(path)
    segments,_=read_file(path,'d');assert segments[0].location_label=='Slide 1' and 'A slide' in segments[0].text
    wb=Workbook();ws=wb.active;ws.title='Experiments';ws.append(['Name','Accuracy']);ws.append(['Model',0.95])
    path=tmp_path/'results.xlsx';wb.save(path)
    segments,_=read_file(path,'d');assert segments[0].location_label=='Sheet "Experiments", Rows 1-1' and 'Name | Accuracy' in segments[0].text

def test_large_table_chunks_repeat_header_without_breaking_rows():
    header='name | value\n'; rows=['record-'+str(i)+'x'*70+' | value\n' for i in range(40)]
    segment=Segment('d',0,header+''.join(rows),'Rows 1-40')
    chunks=chunk_segment(segment,'csv')
    assert len(chunks)>1
    assert all(c.text.startswith(header) for c in chunks)
    assert all(row in ''.join(c.text for c in chunks) for row in rows)
