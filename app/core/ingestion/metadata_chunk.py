"""Conservative first-page metadata extraction: never invent absent fields."""
import re
from pathlib import Path
from .types import Chunk

DOI = re.compile(r'(?<!\w)10\.\d{4,9}/[^\s<>"\[\]]+', re.I)
ARXIV = re.compile(r'\barxiv\s*:\s*(\d{4}\.\d{4,5}(?:v\d+)?)\b', re.I)
HEADING = re.compile(r'^\s*(?:(?:\d+(?:\.\d+)*[.)]?\s+)?(?:introduction|keywords?|background|methods?|related work|references|conclusions?)\b|\d+(?:\.\d+)*[.)]?\s+[A-Z])', re.I)
AFFILIATION = re.compile(r'\b(university|institute|department|laboratory|school|college|faculty|research center|affiliation)\b|@|https?://|\bdoi\b|\barxiv\b',re.I)

def identifiers(text):
    match=DOI.search(text)
    doi=match.group(0).rstrip('.,;:') if match else None
    if doi:
        while doi.endswith(')') and doi.count(')')>doi.count('('): doi=doi[:-1]
    match=ARXIV.search(text)
    return doi, ('arXiv:'+match.group(1)) if match else None

def pdf_fields(path, first_text):
    import fitz
    lines=[]
    with fitz.open(path) as pdf:
        if not len(pdf): return None,[],None
        page=pdf[0]; height=page.rect.height
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines',[]):
                spans=[s for s in line.get('spans',[]) if s['text'].strip()]
                text=''.join(s['text'] for s in line.get('spans',[])).strip()
                if text and spans:
                    lines.append({'text':text,'y0':line['bbox'][1],'y1':line['bbox'][3],
                                  'size':max(s['size'] for s in spans),'flags':max(s.get('flags',0) for s in spans)})
    lines.sort(key=lambda l:(l['y0'],l['text']))
    top=[(i,line) for i,line in enumerate(lines) if line['y0']<height/2 and not re.match(r'abstract\b',line['text'],re.I)]
    if not top: return None,[],None
    title_idx,best=max(top,key=lambda item:item[1]['size'])
    title_lines=[best['text']]; last=best
    for line in lines[title_idx+1:]:
        if abs(line['size']-best['size'])<=.5 and line['y0']-last['y1']<=best['size']*1.5 and not HEADING.match(line['text']):
            title_lines.append(line['text']);last=line
        else: break
    title=' '.join(title_lines)
    abs_idx=next((i for i,l in enumerate(lines) if re.match(r'^abstract\b',l['text'],re.I)),None)
    authors=[]; abstract=None
    if abs_idx is not None and lines[abs_idx]['y0']>last['y0']:
        for line in lines[title_idx+len(title_lines):abs_idx]:
            t=line['text'].strip()
            if AFFILIATION.search(t) or re.match(r'^(doi|arxiv|www\.|\d{4})',t,re.I): continue
            # Require plausible alphabetic names; ignore isolated affiliations or symbols.
            for name in re.split(r'\s*(?:,|;|\band\b|&)\s*',t,flags=re.I):
                name=re.sub(r'\s*\d+\s*$', '',name).strip(' *†‡')
                if len(name.split())>=2 and len(name)<100 and not re.search(r'[\d@/]',name): authors.append(name)
        parts=[re.sub(r'^abstract\b\s*[:.\-–]?\s*','',lines[abs_idx]['text'],flags=re.I)]
        for line in lines[abs_idx+1:]:
            if HEADING.match(line['text']): break
            parts.append(line['text'])
        abstract=' '.join(x.strip() for x in parts if x.strip()) or None
    if abstract is None:
        # PDF extractors sometimes split the abstract heading and body differently.
        match=re.search(r'(?ims)^\s*abstract\b\s*[:.\-–]?\s*(.+?)(?=\n\s*(?:(?:\d+\s+)?(?:introduction|keywords?|background|methods?)\b)|\Z)',first_text)
        if match and match.group(1).strip(): abstract=' '.join(match.group(1).split())
    return title,authors,abstract

def make_metadata(doc_id, path, segments):
    first=segments[0].text if segments else ''
    all_text='\n'.join(s.text for s in segments)
    is_pdf=Path(path).suffix.lower()=='.pdf'
    title=Path(path).name; authors=[]; abstract=None
    if is_pdf and first:
        try:
            parsed_title,authors,abstract=pdf_fields(path,first)
            if parsed_title: title=parsed_title
        except (OSError,ValueError,RuntimeError):
            # The metadata chunk remains useful even when parsing fails.
            pass
    if not abstract:
        abstract=('First page/section fallback: '+first[:1500 if is_pdf else 1000]) if first else 'No text could be extracted'
    doi,arxiv=identifiers(all_text)
    text=f'Document metadata\nTitle: {title}\nAuthors: {", ".join(authors)}\nAbstract: {abstract}\nSource file: {Path(path).name}'
    # PDF metadata describes page one, and its boxes point to the page-one
    # text actually used to construct it rather than invented display labels.
    page=1 if is_pdf and segments else None
    boxes=[box for start,end,box in segments[0].spans if start<1500] if page else None
    chunk=Chunk(f'{doc_id}:metadata',doc_id,-1,0,text,'Document metadata',page,0,len(text),boxes or None,'metadata')
    return chunk, {'title':title,'authors':authors,'abstract':abstract,'doi':doi,'arxiv_id':arxiv}
