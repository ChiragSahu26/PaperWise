from pathlib import Path
import shutil
import pytest
from app.core.ingestion.readers import read_file

FIX=Path(__file__).parent/'fixtures'
def test_two_column_pdf_reading_order():
    segments,w=read_file(FIX/'two_column.pdf','d')
    t=segments[0].text
    assert t.index('LEFT FIRST') < t.index('LEFT SECOND') < t.index('RIGHT FIRST') < t.index('RIGHT SECOND')
    assert segments[0].spans and not w

def test_scanned_pdf_ocr():
    if not shutil.which('tesseract'): pytest.skip('Tesseract is required for the M1 OCR acceptance check')
    events=[]
    segments,w=read_file(FIX/'scanned.pdf','d',lambda n:events.append(n))
    assert events == [1] and not w
    assert 'SCANNED PAPER TEXT' in segments[0].text
    assert 'experiment achieved strong results' in segments[0].text
    assert segments[0].spans
