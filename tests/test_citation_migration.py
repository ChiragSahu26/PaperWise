import sqlite3
import config
from app.db.session import SCHEMA, initialize, connect

def populate(db):
    db.execute("INSERT INTO documents(id,filename,file_path,file_type,status,title,added_at) VALUES ('d','example.pdf','x','pdf','ready','Research title','2026-01-01')")
    db.execute("INSERT INTO chunks(id,doc_id,text,location_label,page,bboxes_json) VALUES ('k','d','A quoted finding','Page 2',2,'[[1,2,3,4]]')")
    db.execute("INSERT INTO chats(id,created_at,updated_at) VALUES ('chat','2026-01-01','2026-01-01')")
    db.execute("INSERT INTO messages(id,chat_id,role,content,created_at) VALUES ('m','chat','assistant','answer','2026-01-01')")
    db.execute("INSERT INTO message_citations(message_id,marker,chunk_id,cited,score,highlight_start,highlight_end) VALUES ('m',1,'k',1,0.9,2,8)")
    db.commit()

def test_migration_preserves_legacy_citations_on_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    old = SCHEMA.read_text().replace('chunk_id TEXT REFERENCES chunks(id) ON DELETE SET NULL, cited', 'chunk_id TEXT REFERENCES chunks(id) ON DELETE CASCADE, cited').replace('  -- snapshot of the citation so old answers survive document deletion (Section 16)\n  doc_title TEXT, location_label TEXT, page INTEGER, snippet TEXT, bboxes_json TEXT,\n','')
    db=connect(); db.executescript(old); populate(db); db.close()
    initialize(); initialize() # migration and restart are idempotent
    db=connect()
    db.execute("DELETE FROM documents WHERE id='d'"); db.commit()
    row=db.execute("SELECT * FROM message_citations").fetchone()
    assert row['chunk_id'] is None
    assert (row['doc_title'],row['location_label'],row['page'],row['snippet'],row['bboxes_json']) == ('Research title','Page 2',2,'A quoted finding','[[1,2,3,4]]')
    assert (row['cited'],row['score'],row['highlight_start'],row['highlight_end']) == (1,0.9,2,8)
    assert not list(db.execute('PRAGMA foreign_key_check'))
    db.close()

def test_fresh_schema_uses_set_null(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    initialize()
    db=connect(); populate(db)
    db.execute("DELETE FROM chunks WHERE id='k'"); db.commit()
    assert db.execute('SELECT chunk_id FROM message_citations').fetchone()[0] is None
    db.close()
