# PaperWise frontend

Scroll-story interface for the PaperWise backend: a crumpled paper unfolds into the title sheet, then into a horizontal stack of white sheets. Each sheet is a tool.

## Run

Backend first (in the `paperwise` folder, second Terminal tab):

    source .venv/bin/activate
    make run

Then here:

    npm install
    npm run dev

Open http://localhost:5173 and scroll. The dev server proxies `/api` to http://127.0.0.1:8000 (override with `PAPERWISE_API=http://host:port npm run dev`).

## Working now
- Scroll scene in light and dark, Skip intro, theme toggle (remembered)
- Ask your papers: streaming answers, numbered citations, evidence label, side PDF with the passage highlighted, Stop
- Add papers: drag and drop, progress, remove, open in reader
- Read with highlights, Settings (model, passages, re-ranker)

## Wired up next
Check a paper, Related chats, Notes, Connections, Similarity check. Their sheets open with a "Wired up next" page.

## No backend handy?
`node mock/server.mjs` starts a small stand-in on port 8000 with one sample paper.
