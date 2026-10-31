"""Bounded batch ingestion with a durable SQLite/Chroma recovery journal."""
import json,logging,threading
from app.db.session import connect
from app.jobs.queue import now
from app.core.ingestion.readers import read_file,iter_pdf
from app.core.ingestion.chunker import chunk_segment
from app.core.ingestion.metadata_chunk import make_metadata,identifiers
from app.core.retrieval import vector_store as vs
log=logging.getLogger(__name__)

class IngestionCancelled(Exception):pass

def ingest_document(doc_id,job_id,publish,cancel=None):
    cancel=cancel or threading.Event()
    def check():
        if cancel.is_set():raise IngestionCancelled('interrupted')
    def progress(status,percent,message):
        with connect() as db:
            db.execute('UPDATE documents SET status=? WHERE id=?',(status,doc_id))
            db.execute('UPDATE jobs SET percent=?,updated_at=? WHERE id=?',(percent,now(),job_id))
        publish({'doc_id':doc_id,'status':status,'percent':percent,'message':message})
    with connect() as db:row=db.execute('SELECT * FROM documents WHERE id=?',(doc_id,)).fetchone()
    if row is None:return
    progress('extracting',5,'Extracting document')
    warnings=[];first=[];found_doi=found_arxiv=None;batch=[];pages=0;has_text=False
    def stage(chunks):
        if not chunks:return
        check();vs.stage_vectors(job_id,chunks)
        with connect() as db:
            db.executemany('INSERT INTO ingest_stage_chunks(job_id,id,doc_id,segment_index,chunk_index,type,text,location_label,page,char_start,char_end,bboxes_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                [(job_id,c.id,c.doc_id,c.segment_index,c.chunk_index,c.type,c.text,c.location_label,c.page,c.char_start,c.char_end,json.dumps(c.bboxes) if c.bboxes is not None else None) for c in chunks])
    try:
        if row['file_type']=='pdf':
            import fitz
            with fitz.open(row['file_path']) as pdf:total=len(pdf)
            segments=iter_pdf(row['file_path'],doc_id,warnings,lambda page:progress('ocr',min(65,5+int(60*page/max(total,1))),f'OCR page {page}'))
        else:
            segments,warnings=read_file(row['file_path'],doc_id);total=len(segments)
        for seg in segments:
            check();pages+=1
            if not first:first=[seg]
            doi,arxiv=identifiers(seg.text);found_doi=found_doi or doi;found_arxiv=found_arxiv or arxiv
            if seg.text.strip():has_text=True;batch.extend(chunk_segment(seg,row['file_type']))
            while len(batch)>=64:stage(batch[:64]);del batch[:64]
            if pages%16==0:progress('extracting',min(65,5+int(60*pages/max(total,1))),f'Processed {pages} of {total} pages/sections')
        metadata,fields=make_metadata(doc_id,row['file_path'],first)
        fields['doi']=found_doi;fields['arxiv_id']=found_arxiv
        batch.insert(0,metadata);stage(batch)
        if not has_text:warnings.append('No text could be extracted')
        check();progress('indexing',75,'Committing indexed batches')
        # Backup first; no live vectors change until the recovery journal is durable.
        with vs._lock:
            vs.backup_vectors(doc_id,job_id);check()
            with connect() as db:db.execute('INSERT OR REPLACE INTO ingest_recovery(doc_id,job_id) VALUES (?,?)',(doc_id,job_id))
            try:
                with connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    if not db.execute('SELECT 1 FROM documents WHERE id=?',(doc_id,)).fetchone():raise RuntimeError('document deleted')
                    vs.apply_staged_vectors(doc_id,job_id,db)
                    from app.core.knowledge.graph import remove_contributions
                    from app.core.knowledge.conflicts import recompute
                    remove_contributions(db,doc_id)
                    db.execute('DELETE FROM paper_references WHERE source_doc_id=?',(doc_id,))
                    db.execute('''UPDATE chunks SET (segment_index,chunk_index,type,text,location_label,page,char_start,char_end,bboxes_json) =
                      (SELECT segment_index,chunk_index,type,text,location_label,page,char_start,char_end,bboxes_json FROM ingest_stage_chunks s WHERE s.job_id=? AND s.id=chunks.id)
                      WHERE doc_id=? AND EXISTS (SELECT 1 FROM ingest_stage_chunks s WHERE s.job_id=? AND s.id=chunks.id)''',(job_id,doc_id,job_id))
                    db.execute('''INSERT INTO chunks(id,doc_id,segment_index,chunk_index,type,text,location_label,page,char_start,char_end,bboxes_json)
                      SELECT s.id,s.doc_id,s.segment_index,s.chunk_index,s.type,s.text,s.location_label,s.page,s.char_start,s.char_end,s.bboxes_json FROM ingest_stage_chunks s
                      WHERE s.job_id=? AND NOT EXISTS (SELECT 1 FROM chunks c WHERE c.id=s.id)''',(job_id,))
                    db.execute('DELETE FROM chunks WHERE doc_id=? AND NOT EXISTS (SELECT 1 FROM ingest_stage_chunks s WHERE s.job_id=? AND s.id=chunks.id)',(doc_id,job_id))
                    recompute(db)
                    db.execute('''UPDATE documents SET status='ready',error=NULL,warnings_json=?,page_count=?,title=?,authors_json=?,abstract=?,doi=?,arxiv_id=?,version=version+1 WHERE id=?''',
                       (json.dumps(warnings),pages if row['file_type']=='pdf' else None,fields['title'],json.dumps(fields['authors']),fields['abstract'],fields['doi'],fields['arxiv_id'],doc_id))
                    db.execute("UPDATE jobs SET status='done',percent=100,updated_at=? WHERE id=?",(now(),job_id))
                    db.execute('DELETE FROM ingest_recovery WHERE doc_id=?',(doc_id,))
            except BaseException:
                vs.restore_backup(doc_id,job_id)
                with connect() as db:db.execute('DELETE FROM ingest_recovery WHERE doc_id=?',(doc_id,))
                raise
        publish({'doc_id':doc_id,'status':'ready','percent':100,'message':'Ready'})
    finally:
        # Never erase the backup if recovery itself failed.
        with connect() as db:recovery=db.execute('SELECT 1 FROM ingest_recovery WHERE doc_id=?',(doc_id,)).fetchone()
        if not recovery:
            try:vs.cleanup_stage(job_id)
            except Exception:log.warning('Failed to clear ingestion staging',exc_info=True)
            with connect() as db:db.execute('DELETE FROM ingest_stage_chunks WHERE job_id=?',(job_id,))
