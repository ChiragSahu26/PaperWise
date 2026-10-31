PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE documents (
  id TEXT PRIMARY KEY, filename TEXT NOT NULL, file_path TEXT NOT NULL, file_type TEXT NOT NULL,
  status TEXT NOT NULL, error TEXT, warnings_json TEXT DEFAULT '[]',
  page_count INTEGER, title TEXT, authors_json TEXT DEFAULT '[]', abstract TEXT,
  doi TEXT, arxiv_id TEXT, version INTEGER DEFAULT 1,
  added_at TEXT NOT NULL, sha256 TEXT
);

CREATE TABLE chunks (
  id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  segment_index INTEGER, chunk_index INTEGER, type TEXT DEFAULT 'text',   -- 'text' or 'metadata'
  text TEXT NOT NULL, location_label TEXT NOT NULL, page INTEGER,
  char_start INTEGER, char_end INTEGER, bboxes_json TEXT
);
CREATE INDEX idx_chunks_doc ON chunks(doc_id);

CREATE TABLE chats (
  id TEXT PRIMARY KEY, title TEXT, summary TEXT, pinned INTEGER DEFAULT 0,
  topic_id TEXT, model TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE chat_documents (
  chat_id TEXT REFERENCES chats(id) ON DELETE CASCADE, doc_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
  PRIMARY KEY (chat_id, doc_id)
);

CREATE TABLE messages (
  id TEXT PRIMARY KEY, chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  role TEXT NOT NULL,                 -- 'user' or 'assistant'
  content TEXT NOT NULL, mode TEXT, model TEXT, refused INTEGER DEFAULT 0,
  confidence_level TEXT, confidence_score REAL, tokens INTEGER, latency_ms INTEGER,
  faithfulness_json TEXT, debug_json TEXT,   -- debug: expanded query, ranked chunks, final prompt, warnings
  created_at TEXT NOT NULL
);
CREATE TABLE message_citations (
  message_id TEXT REFERENCES messages(id) ON DELETE CASCADE, marker INTEGER,
  chunk_id TEXT REFERENCES chunks(id) ON DELETE SET NULL, cited INTEGER DEFAULT 0, score REAL,
  -- snapshot of the citation so old answers survive document deletion (Section 16)
  doc_title TEXT, location_label TEXT, page INTEGER, snippet TEXT, bboxes_json TEXT,
  highlight_start INTEGER, highlight_end INTEGER,
  PRIMARY KEY (message_id, marker)
);

CREATE TABLE topics (id TEXT PRIMARY KEY, label TEXT, updated_at TEXT);
CREATE TABLE similar_dismissals (chat_id TEXT, other_chat_id TEXT, PRIMARY KEY (chat_id, other_chat_id));

CREATE TABLE notes (
  id TEXT PRIMARY KEY, body_md TEXT NOT NULL, tags_json TEXT DEFAULT '[]',
  doc_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
  chat_id TEXT REFERENCES chats(id) ON DELETE SET NULL,
  message_id TEXT REFERENCES messages(id) ON DELETE SET NULL,
  anchor_json TEXT,                   -- {page, bboxes, quote}
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE paper_intel (
  doc_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
  data_json TEXT NOT NULL, fetched_at TEXT NOT NULL
);
CREATE TABLE resources_cache (
  doc_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
  data_json TEXT NOT NULL, fetched_at TEXT NOT NULL
);

CREATE TABLE graph_nodes (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, label TEXT NOT NULL, norm_label TEXT NOT NULL
);
CREATE TABLE graph_node_docs (node_id TEXT REFERENCES graph_nodes(id) ON DELETE CASCADE,
  doc_id TEXT REFERENCES documents(id) ON DELETE CASCADE, PRIMARY KEY (node_id, doc_id));
CREATE TABLE graph_edges (
  id TEXT PRIMARY KEY, source_id TEXT REFERENCES graph_nodes(id) ON DELETE CASCADE,
  target_id TEXT REFERENCES graph_nodes(id) ON DELETE CASCADE, type TEXT NOT NULL,
  chunk_ids_json TEXT DEFAULT '[]'
);

CREATE TABLE claims (
  id TEXT PRIMARY KEY, doc_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
  task TEXT, dataset TEXT, metric TEXT, value REAL, value_text TEXT, setting TEXT, unit TEXT,
  chunk_id TEXT REFERENCES chunks(id) ON DELETE SET NULL
);
CREATE TABLE conflicts (
  id TEXT PRIMARY KEY, dataset TEXT, metric TEXT, setting TEXT,
  entries_json TEXT NOT NULL, note TEXT, created_at TEXT
);

CREATE TABLE jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, percent REAL DEFAULT 0,
  payload_json TEXT, result_json TEXT, error TEXT, priority INTEGER DEFAULT 5,
  created_at TEXT, updated_at TEXT
);

CREATE TABLE similarity_reports (id TEXT PRIMARY KEY, mode TEXT, result_json TEXT, created_at TEXT);
CREATE TABLE settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);

CREATE TABLE similarity_checks (id TEXT PRIMARY KEY, scope TEXT NOT NULL, target_doc_id TEXT, target_text TEXT, result_json TEXT, created_at TEXT NOT NULL);

CREATE TABLE ingest_stage_chunks (job_id TEXT NOT NULL, id TEXT NOT NULL, doc_id TEXT NOT NULL, segment_index INTEGER, chunk_index INTEGER, type TEXT, text TEXT, location_label TEXT, page INTEGER, char_start INTEGER, char_end INTEGER, bboxes_json TEXT, PRIMARY KEY(job_id,id));
CREATE TABLE ingest_recovery (doc_id TEXT PRIMARY KEY,job_id TEXT NOT NULL);

CREATE TABLE paper_references (source_doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,target_doi TEXT NOT NULL,PRIMARY KEY(source_doc_id,target_doi));
