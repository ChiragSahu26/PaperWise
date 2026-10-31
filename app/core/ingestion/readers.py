"""Local document readers. No external content or embedded URLs are fetched."""
from collections import Counter
import csv
from pathlib import Path
import re
from .types import Segment
from .columns import order_blocks
import config

SUPPORTED = {'pdf','docx','pptx','txt','md','csv','xlsx'}

def segment(doc_id,index,text,label,page=None,spans=None):
    return Segment(doc_id,index,text,label,page,spans or [])

def sniff(path):
    path = Path(path)
    ext = path.suffix.lower().lstrip('.')
    if ext not in SUPPORTED: raise ValueError('UNSUPPORTED_FILE')
    with path.open('rb') as f: head = f.read(4096)
    if ext == 'pdf' and not head.startswith(b'%PDF-'): raise ValueError('UNSUPPORTED_FILE')
    if ext in ('docx','pptx','xlsx'):
        from zipfile import ZipFile, BadZipFile
        try:
            with ZipFile(path) as archive:
                names = set(archive.namelist())
                required = {'docx':'word/document.xml','pptx':'ppt/presentation.xml','xlsx':'xl/workbook.xml'}[ext]
                if required not in names or '[Content_Types].xml' not in names: raise ValueError('UNSUPPORTED_FILE')
        except (BadZipFile, OSError): raise ValueError('UNSUPPORTED_FILE')
    if ext in ('txt','md','csv'):
        if b'\x00' in head: raise ValueError('UNSUPPORTED_FILE')
        import codecs
        try:
            decoder=codecs.getincrementaldecoder('utf-8-sig')()
            with path.open('rb') as source:
                while chunk:=source.read(1024*1024):
                    if b'\x00' in chunk: raise ValueError('UNSUPPORTED_FILE')
                    decoder.decode(chunk,final=False)
                decoder.decode(b'',final=True)
        except UnicodeDecodeError as e: raise ValueError('UNSUPPORTED_FILE') from e
    return ext

def read_file(path, doc_id, on_ocr=None):
    ext = sniff(path)
    if ext == 'pdf': return read_pdf(path,doc_id,on_ocr)
    if ext == 'docx': return read_docx(path,doc_id), []
    if ext == 'pptx': return read_pptx(path,doc_id), []
    if ext in ('txt','md'): return read_text(path,doc_id,ext), []
    return read_tables(path,doc_id,ext), []

def iter_pdf(path, doc_id, warnings, on_ocr=None):
    import fitz
    with fitz.open(path) as pdf:
        # Count repeatable margin text without retaining all page content in memory.
        margin_counts = Counter()
        for page_index, p in enumerate(pdf):
            if page_index >= 100: break
            per_page=set()
            for b in p.get_text('blocks'):
                if len(b)>6 and b[6] != 0: continue
                if b[1] <= p.rect.height*.05 or b[3] >= p.rect.height*.95:
                    per_page.add(' '.join(b[4].split()))
            margin_counts.update(per_page)
        for i, p in enumerate(pdf):
            blocks=[]
            for b in p.get_text('blocks'):
                if len(b)>6 and b[6] != 0: continue
                text = b[4].strip()
                margin = b[1] <= p.rect.height*.05 or b[3] >= p.rect.height*.95
                if not text or (margin and (margin_counts[' '.join(text.split())] >= 3 or re.fullmatch(r'\d+',text))): continue
                blocks.append((b[0],b[1],b[2],b[3],text))
            blocks = order_blocks(blocks,p.rect.width)
            is_ocr = False
            if len(re.sub(r'\s','', ''.join(b[4] for b in blocks))) < config.OCR_MIN_CHARS_PER_PAGE:
                if on_ocr: on_ocr(i+1)
                try:
                    blocks = ocr_page(p)
                    is_ocr = False
                except Exception:
                    warnings.append(f'OCR_FAILED: Page {i+1}')
            text_parts, spans, offset, previous = [], [], 0, None
            for x0,y0,x1,y1,text in blocks:
                if previous is not None:
                    # OCR yields words, not text blocks: preserve spaces on each line.
                    same_line = is_ocr and abs(y0-previous[1]) < max(2,(y1-y0)*0.5) and x0 >= previous[0]
                    separator = ' ' if same_line else '\n'
                    text_parts.append(separator); offset += len(separator)
                text_parts.append(text)
                spans.append((offset,offset+len(text),[float(x0),float(y0),float(x1),float(y1)]))
                offset += len(text); previous=(x0,y0)
            yield segment(doc_id,i,''.join(text_parts),f'Page {i+1}',i+1,spans)


def read_pdf(path,doc_id,on_ocr=None):
    warnings=[]
    return list(iter_pdf(path,doc_id,warnings,on_ocr)),warnings

def ocr_page(page):
    import io
    import fitz, pytesseract
    from PIL import Image
    scale = config.OCR_DPI / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(scale,scale), alpha=False)
    data = pytesseract.image_to_data(Image.open(io.BytesIO(pix.tobytes('png'))),output_type=pytesseract.Output.DICT)
    # Tesseract gives word boxes and line identifiers. Reassemble lines before
    # column ordering, otherwise tiny baseline differences scramble words.
    lines={}
    for i,word in enumerate(data['text']):
        if not word.strip(): continue
        x,y,w,h = (data[k][i]/scale for k in ('left','top','width','height'))
        key=tuple(data[k][i] for k in ('block_num','par_num','line_num'))
        lines.setdefault(key,[]).append((x,y,x+w,y+h,word.strip()))
    result=[]
    for words in lines.values():
        words.sort(key=lambda item:item[0])
        result.append((min(w[0] for w in words),min(w[1] for w in words),
                       max(w[2] for w in words),max(w[3] for w in words),
                       ' '.join(w[4] for w in words)))
    return order_blocks(result,page.rect.width)

def read_text(path, doc_id, ext):
    text = Path(path).read_text(encoding='utf-8-sig')
    # MD headings become labels and section boundaries.
    sections = re.split(r'(?m)(?=^#{1,6}\s+)',text) if ext == 'md' else [text]
    out=[]
    for section in sections:
        if not section.strip(): continue
        first=section.splitlines()[0]
        heading=re.match(r'^#{1,6}\s+(.+)',first) if ext=='md' else None
        label=f'Section: {heading.group(1).strip()}' if heading else None
        parts=re.split(r'(?<=\n)\s*\n',section)
        buf=''
        def add(s):
            out.append(segment(doc_id,len(out),s,label or f'Part {len(out)+1}'))
        for part in parts:
            if buf and len(buf)+len(part)>config.CHUNK_SIZE_TEXT: add(buf); buf=''
            buf += part
        if buf: add(buf)
    return out

def read_docx(path, doc_id):
    from docx import Document
    from docx.text.paragraph import Paragraph
    from docx.table import Table
    from docx.oxml.ns import qn
    doc=Document(path); out=[]; buf=[]; heading=None; count=0; begin=1
    def flush():
        nonlocal buf,begin
        if buf:
            out.append(segment(doc_id,len(out),'\n'.join(buf),f'Section: {heading}' if heading else f'Paragraphs {begin}-{count}'))
            buf=[]; begin=count+1
    for child in doc.element.body.iterchildren():
        if child.tag == qn('w:p'):
            p=Paragraph(child,doc); text=p.text.strip()
            if not text: continue
            is_heading=p.style and p.style.name.lower().startswith('heading')
            if is_heading: flush(); heading=text
            count+=1; buf.append(text)
            if len(buf)>=config.DOCX_PARAS_PER_SEGMENT: flush()
        elif child.tag == qn('w:tbl'):
            t=Table(child,doc)
            buf.extend(' | '.join(cell.text for cell in row.cells) for row in t.rows)
    flush(); return out

def read_pptx(path,doc_id):
    from pptx import Presentation
    slides=Presentation(path).slides; out=[]
    for i,slide in enumerate(slides):
        pieces=[]
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text.strip(): pieces.append(shape.text.strip())
            if shape.has_table:
                pieces.extend(' | '.join(c.text for c in row.cells) for row in shape.table.rows)
        if slide.has_notes_slide:
            notes=slide.notes_slide.notes_text_frame.text.strip()
            if notes: pieces.append('Notes: '+notes)
        out.append(segment(doc_id,i,'\n'.join(pieces),f'Slide {i+1}'))
    return out

def read_tables(path,doc_id,ext):
    if ext=='csv':
        with open(path,encoding='utf-8-sig',newline='') as f: sheets=[(None,list(csv.reader(f)))]
    else:
        from openpyxl import load_workbook
        book=load_workbook(path,read_only=True,data_only=True)
        try: sheets=[(s.title,list(s.iter_rows(values_only=True))) for s in book]
        finally: book.close()
    out=[]
    for name,rows in sheets:
        if not rows: continue
        def row_text(row): return ' | '.join('' if x is None else str(x) for x in row)
        header=row_text(rows[0]); data=rows[1:]
        for pos in range(0,len(data),config.TABLE_ROWS_PER_SEGMENT):
            part=data[pos:pos+config.TABLE_ROWS_PER_SEGMENT]
            label=f'Rows {pos+1}-{pos+len(part)}'
            if name is not None: label=f'Sheet "{name}", '+label
            out.append(segment(doc_id,len(out),'\n'.join([header]+[row_text(r) for r in part]),label))
    return out
