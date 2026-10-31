import sqlite3
from pathlib import Path
import config

SCHEMA = Path(__file__).with_name('schema.sql')
SNAPSHOT_COLUMNS = ('doc_title', 'location_label', 'page', 'snippet', 'bboxes_json')

def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(config.DATA_DIR / 'paperwise.sqlite3', timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    return db

def migrate_citations(db):
    """Upgrade legacy citation rows before any further chunks are deleted.

    Copies snapshots from existing documents/chunks, retaining pre-existing snapshots
    where present. Rows already lost by the former CASCADE cannot be recovered.
    """
    db.execute('BEGIN IMMEDIATE')
    try:
        columns = {r['name'] for r in db.execute('PRAGMA table_info(message_citations)')}
        chunk_fk = next((r for r in db.execute('PRAGMA foreign_key_list(message_citations)')
                         if r['from'] == 'chunk_id'), None)
        if set(SNAPSHOT_COLUMNS).issubset(columns) and chunk_fk and chunk_fk['on_delete'].upper() == 'SET NULL':
            db.commit()
            return
        required = {'message_id','marker','chunk_id','cited','score','highlight_start','highlight_end'}
        if not required.issubset(columns):
            raise RuntimeError('Unrecognized message_citations schema; automatic migration aborted')
        db.execute('''CREATE TABLE message_citations_new (
          message_id TEXT REFERENCES messages(id) ON DELETE CASCADE, marker INTEGER,
          chunk_id TEXT REFERENCES chunks(id) ON DELETE SET NULL, cited INTEGER DEFAULT 0, score REAL,
          doc_title TEXT, location_label TEXT, page INTEGER, snippet TEXT, bboxes_json TEXT,
          highlight_start INTEGER, highlight_end INTEGER,
          PRIMARY KEY (message_id, marker))''')
        fallback = {'doc_title': 'COALESCE(d.title, d.filename)', 'location_label': 'c.location_label',
                    'page': 'c.page', 'snippet': 'substr(c.text,1,300)', 'bboxes_json': 'c.bboxes_json'}
        expressions = [f'COALESCE(mc.{name}, {fallback[name]})' if name in columns else fallback[name]
                       for name in SNAPSHOT_COLUMNS]
        db.execute('''INSERT INTO message_citations_new
          (message_id,marker,chunk_id,cited,score,doc_title,location_label,page,snippet,bboxes_json,highlight_start,highlight_end)
          SELECT mc.message_id,mc.marker,mc.chunk_id,mc.cited,mc.score,''' + ','.join(expressions) + ''',
                 mc.highlight_start,mc.highlight_end
          FROM message_citations mc LEFT JOIN chunks c ON c.id=mc.chunk_id
          LEFT JOIN documents d ON d.id=c.doc_id''')
        db.execute('DROP TABLE message_citations')
        db.execute('ALTER TABLE message_citations_new RENAME TO message_citations')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign key check failed during citation migration')
        db.commit()
    except Exception:
        db.rollback()
        raise

def initialize():
    db = connect()
    try:
        # The supplied schema describes a new database. IF NOT EXISTS allows normal restarts.
        schema = SCHEMA.read_text().replace('CREATE TABLE ', 'CREATE TABLE IF NOT EXISTS ').replace('CREATE INDEX ', 'CREATE INDEX IF NOT EXISTS ')
        db.executescript(schema)
        migrate_citations(db)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(documents)")}
        if "sha256" not in columns:
            db.execute("ALTER TABLE documents ADD COLUMN sha256 TEXT")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256) WHERE sha256 IS NOT NULL")
        # Restore highlights for metadata indexed by earlier versions where possible.
        import json
        old=db.execute("SELECT c.id,c.doc_id FROM chunks c JOIN documents d ON d.id=c.doc_id WHERE c.type='metadata' AND d.file_type='pdf' AND c.page IS NULL").fetchall()
        for row in old:
            boxes=[]
            for part in db.execute("SELECT bboxes_json FROM chunks WHERE doc_id=? AND page=1 AND type='text' ORDER BY chunk_index",(row['doc_id'],)):
                if part[0]: boxes.extend(json.loads(part[0]))
            if boxes: db.execute("UPDATE chunks SET page=1,bboxes_json=? WHERE id=?",(json.dumps(boxes),row['id']))
        if 'unit' not in {r['name'] for r in db.execute('PRAGMA table_info(claims)')}:
            db.execute('ALTER TABLE claims ADD COLUMN unit TEXT')
        fts_exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notes_fts'").fetchone()
        db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(body_md,tags_json,content='notes',content_rowid='rowid')")
        db.executescript("""
        CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
          INSERT INTO notes_fts(rowid,body_md,tags_json) VALUES (new.rowid,new.body_md,new.tags_json);
        END;
        CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
          INSERT INTO notes_fts(notes_fts,rowid,body_md,tags_json) VALUES ('delete',old.rowid,old.body_md,old.tags_json);
        END;
        CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
          INSERT INTO notes_fts(notes_fts,rowid,body_md,tags_json) VALUES ('delete',old.rowid,old.body_md,old.tags_json);
          INSERT INTO notes_fts(rowid,body_md,tags_json) VALUES (new.rowid,new.body_md,new.tags_json);
        END;
        """)
        if not fts_exists: db.execute("INSERT INTO notes_fts(notes_fts) VALUES ('rebuild')")
        db.commit()
    finally:
        db.close()
