from .types import Chunk
import config

def split_ranges(text, size, overlap):
    """Ranges retain exact source offsets; prefer paragraph and sentence boundaries."""
    if size <= 0 or not 0 <= overlap < size: raise ValueError('invalid chunk size/overlap')
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            for sep in ('\n\n','\n','. ',' '):
                pos = text.rfind(sep, start + max(1, size // 2), end)
                if pos >= 0:
                    end = pos + len(sep)
                    break
        yield start, end
        if end == len(text): break
        start = max(start + 1, end - overlap)

def line_ranges(text,size,table=False):
    """Split only at line boundaries; an oversized row is never divided."""
    lines=text.splitlines(keepends=True)
    header=lines[0] if table and lines else ''
    pos=len(header); group_start=pos; group_len=0
    for line in lines[1:] if table else lines:
        if group_len and group_len+len(line)+len(header)>size:
            yield group_start,group_start+group_len,header
            group_start=pos; group_len=0
        group_len+=len(line); pos+=len(line)
    if group_len: yield group_start,group_start+group_len,header
    elif table and header: yield 0,len(header),''

def chunk_segment(segment, file_type):
    is_text = file_type in ('txt','md')
    size = config.CHUNK_SIZE_TEXT if is_text else config.CHUNK_SIZE_PDF
    special=file_type in ('csv','xlsx','pptx')
    if special and len(segment.text) <= 2*size:
        ranges=[(0,len(segment.text),'')]
    elif special:
        ranges=list(line_ranges(segment.text,size,file_type in ('csv','xlsx')))
    else:
        ranges=[(start,end,'') for start,end in split_ranges(segment.text,size,config.CHUNK_OVERLAP_PDF)]
    chunks = []
    for i,(start,end,prefix) in enumerate(ranges):
        boxes = [box for a,b,box in segment.spans if a < end and b > start] if segment.page is not None else None
        chunks.append(Chunk(f'{segment.doc_id}:{segment.index}:{i}',segment.doc_id,segment.index,i,
                            prefix+segment.text[start:end],segment.location_label,segment.page,start,end,boxes))
    return chunks
