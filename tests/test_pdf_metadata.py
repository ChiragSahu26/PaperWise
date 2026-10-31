import fitz
from app.core.ingestion.readers import read_file
from app.core.ingestion.metadata_chunk import make_metadata,identifiers

def test_pdf_title_authors_abstract_and_identifiers(tmp_path):
    path=tmp_path/'paper.pdf'; doc=fitz.open(); p=doc.new_page(width=600,height=800)
    p.insert_text((60,80),'Learning from Research Papers',fontsize=20)
    p.insert_text((60,110),'Alice Smith, Bob Jones',fontsize=11)
    p.insert_text((60,130),'University of Example',fontsize=10)
    p.insert_text((60,160),'Abstract: This study examines methods for evidence retrieval.',fontsize=10)
    p.insert_text((60,177),'We show that local approaches improve reproducibility.',fontsize=10)
    p.insert_text((60,205),'1 Introduction',fontsize=12)
    p.insert_text((60,225),'This introduction must not appear in the abstract.',fontsize=10)
    p.insert_text((60,250),'DOI: 10.1234/example.123 and arXiv:2410.01234',fontsize=10)
    doc.save(path);doc.close()
    segments,_=read_file(path,'d'); chunk,fields=make_metadata('d',path,segments)
    assert fields['title']=='Learning from Research Papers'
    assert fields['authors']==['Alice Smith','Bob Jones']
    assert fields['abstract']=='This study examines methods for evidence retrieval. We show that local approaches improve reproducibility.'
    assert fields['doi']=='10.1234/example.123' and fields['arxiv_id']=='arXiv:2410.01234'
    assert 'Authors: Alice Smith, Bob Jones' in chunk.text

def test_identifiers_and_fallback(tmp_path):
    from app.core.ingestion.types import Segment
    assert identifiers('https://doi.org/10.1234/alpha(b). ArXiv: 2201.12345v2') == ('10.1234/alpha(b)','arXiv:2201.12345v2')
    path=tmp_path/'empty.pdf';doc=fitz.open();doc.new_page();doc.save(path);doc.close()
    _,fields=make_metadata('d',path,[Segment('d',0,'','Page 1',1)])
    assert fields['abstract']=='No text could be extracted' and fields['doi'] is None
