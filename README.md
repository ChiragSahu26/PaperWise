# PaperWise backend

Local-first FastAPI backend for `SPEC.md`, implementing milestones M1–M9. See `DECISIONS.md` for test evidence, limitations, and which checks used mocks. A real Ollama smoke run has not been performed in this environment.

## Features

- Background document ingestion, PDF/OCR/Office/text/table readers, metadata, Chroma embeddings, hybrid retrieval and cross-encoder reranking.
- Ollama grounded answer streaming, citations, PDF highlight boxes, refusal handling, comparison mode and cancellation.
- Chat titles/summaries, similar chats, duplicate questions, topic groups, dismissals and Markdown export.
- Opt-in paper intelligence, evidence-strength breakdown, local concept extraction and learning links; online requests are disabled by default.
- Notes with FTS5 body/tag search, PDF anchors, Markdown export and optional retrieval inclusion.
- Provenance-linked knowledge graph, extracted claims and configurable cross-paper conflict detection.
- Per-answer NLI faithfulness (local LLM fallback), background similarity reports, streaming progress and persistent jobs.
- Batched PDF ingestion with durable cross-store recovery and cooperative shutdown.

## Setup

Use Python 3.11+ and, on macOS, install Tesseract and Ollama:

```bash
brew install tesseract
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
```

The application loads embedding, reranking and NLI weights from the local cache only. If NLI weights are unavailable, faithfulness falls back to the local Ollama judge. Provision them once while online, or copy a prepopulated cache:

```bash
python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2'); CrossEncoder('cross-encoder/nli-deberta-v3-small')"
ollama pull qwen2.5:14b-instruct
```

Choose a different Ollama model if needed for available memory. Tesseract must be on `PATH`. The application does not send uploaded text to hosted LLMs.

## Run

```bash
make run
curl http://127.0.0.1:8000/api/v1/health
curl -F 'files=@paper.pdf' http://127.0.0.1:8000/api/v1/documents
```

Wait for document status `ready`; then create a chat with `POST /api/v1/chats` and ask through `POST /api/v1/chats/{id}/messages` (SSE). Progress streams at `/api/v1/documents/events`; API docs are at `/docs` and the generated contract is `openapi.json`. Bind defaults to `127.0.0.1`; there is no authentication.

Configuration defaults live in `config.py`, overridable with environment variables or `.env`. `PUT /api/v1/settings` can set `online_lookups` and `notes_in_retrieval`. External lookups are off by default; enabling them sends identifiers, paper titles, concept names or explicitly identified GitHub repository names—not document text—to the relevant providers. Optional credentials are `SEMANTIC_SCHOLAR_KEY`, `OPENALEX_API_KEY`, `GITHUB_TOKEN`, `YOUTUBE_API_KEY`, and `CONTACT_EMAIL`.

Paper intelligence is at `/api/v1/documents/{id}/intelligence`; learning resources are at `/resources` and can initially return `pending`. Notes use `/api/v1/notes`; FTS queries use `q`, with optional `doc_id`, `chat_id` and `tag` filters. Only document-attached notes from selected documents enter retrieval, and only when explicitly enabled.

## Graph, faithfulness and similarity

`GET /api/v1/graph`, `GET /api/v1/graph/nodes/{id}` and `GET /api/v1/conflicts` expose background extraction results. Only explicit extracted relations and source passages are included; graph extraction may lag indexing. Optional Semantic Scholar references are used only when online lookup is enabled; citation edges require both papers and an extracted passage mentioning the target.

After an answer, the optional `faithfulness` SSE event may arrive after `done`; otherwise poll `GET /api/v1/chats/{id}/messages/{mid}`. Results use original-answer character offsets. They are model judgments, not proofs. Configure `NLI_MODEL`, `FAITHFULNESS_SSE_WAIT_S`, `CONFLICT_PERCENT_TOLERANCE` and `CONFLICT_RAW_RELATIVE_TOLERANCE` as needed.

Start a local similarity job with `POST /api/v1/similarity-checks` using `{"mode":"my_writing","text":"...","exclude_quotes":true}` or `{"mode":"corpus","doc_id":"..."}`. Poll `/api/v1/jobs/{job_id}` and fetch `/api/v1/similarity-checks/{check_id}`. `overall_percent` is a word-weighted percentage; a match indicates similarity, not plagiarism. Web mode is disabled and never sends text.

## Verify

```bash
make test
make openapi
python scripts/run_evaluation.py --compare-modes --questions tests/eval/questions.json --k 5
# With the backend, Ollama and local weights running on your Mac (unmocked):
python scripts/smoke_real.py --model qwen2.5:14b-instruct
# Optional slower answer-quality evaluation: 20 fixture questions + 10 unanswerable
python scripts/run_evaluation.py --answers --models qwen2.5:14b-instruct
# Opt-in: contacts public services using a known DOI:
python scripts/check_online_intelligence.py
```

Real-embedding and NLI tests skip with a clear message when the respective model cache is empty. OCR checks need Tesseract. The evaluation seeds two synthetic fixture documents if absent; use a disposable `DATA_DIR` to keep them out of an existing collection. The live check may be rate-limited and prints unavailable provider parts rather than inventing values.

To inspect a PDF citation visually, save the citation JSON returned by the API and run:

```bash
python scripts/render_highlights.py paper.pdf citation.json --output highlight_debug.png
```

The real smoke script uploads the bundled fixture through the running API and prints the streamed answers, citations, refusal, time to first token, stream-token rate and pass/fail. It exits nonzero on failure. `--api-url` and `--model` are optional. The answer-quality mode writes `answer_eval_results.json` and `answer_eval_results.md`; unavailable faithfulness judgments are excluded and counted. These scripts are not evidence of a real model pass until actually run on your system.

The source archive excludes runtime data and model caches. Prompt grounding is not a guarantee of factual correctness: check the cited sources.
