// Tiny stand-in for the PaperWise backend (same response shapes) so the UI can be developed offline.
import http from 'node:http'
import fs from 'node:fs'
const doc = { id: 'd1', filename: 'florabench.pdf', file_type: 'pdf', status: 'ready', page_count: 1, title: 'FloraBench: Leaf Disease Detection', authors: ['A. Rao', 'M. Chen'], added_at: new Date().toISOString(), warnings: [], intelligence_badge: null }
let docs = [doc], chats = [], msgs = {}
const json = (res, o, c = 200) => { res.writeHead(c, { 'content-type': 'application/json' }); res.end(JSON.stringify(o)) }
const body = (req) => new Promise((r) => { let b = ''; req.on('data', (d) => (b += d)); req.on('end', () => r(b ? JSON.parse(b) : {})) })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://x'); const p = u.pathname.replace('/api/v1', ''); const m = req.method
  if (p === '/health') return json(res, { status: 'ok', version: 'mock', ollama: { up: true, models: ['qwen2.5:14b-instruct'] }, internet: false, online_lookups_enabled: false, device: 'mock' })
  if (p === '/models') return json(res, [{ name: 'qwen2.5:14b-instruct', size_gb: 9, family: 'qwen2', params: '14B', quant: 'Q4' }])
  if (p === '/settings') return json(res, { default_model: 'qwen2.5:14b-instruct', top_k: 6, use_reranker: true, hybrid_weights: [0.5, 0.5], num_ctx: 8192, online_lookups: false, similarity_weights: {}, notes_in_retrieval: false })
  if (p === '/documents' && m === 'GET') return json(res, docs)
  if (p === '/documents/events') { res.writeHead(200, { 'content-type': 'text/event-stream' }); return res.write(': hi\n\n') }
  if (p === '/documents/d1/file') { res.writeHead(200, { 'content-type': 'application/pdf' }); return res.end(fs.readFileSync(new URL('./sample.pdf', import.meta.url))) }
  if (p === '/chats' && m === 'GET') return json(res, chats)
  if (p === '/chats' && m === 'POST') { const b = await body(req); const c = { id: 'c' + (chats.length + 1), title: 'New chat', summary: null, updated_at: new Date().toISOString(), doc_ids: b.doc_ids ?? ['d1'], pinned: false, topic_id: null, model: null }; chats.push(c); msgs[c.id] = []; return json(res, c, 201) }
  let cm = p.match(/^\/chats\/(\w+)$/)
  if (cm && m === 'GET') return json(res, { ...chats.find((c) => c.id === cm[1]), messages: msgs[cm[1]] ?? [] })
  let mm = p.match(/^\/chats\/(\w+)\/messages$/)
  if (mm && m === 'GET') return json(res, msgs[mm[1]] ?? [])
  if (mm && m === 'POST') {
    const b = await body(req); const id = 'm' + Date.now()
    res.writeHead(200, { 'content-type': 'text/event-stream' })
    const ev = (n, d) => res.write(`event: ${n}\ndata: ${JSON.stringify(d)}\n\n`)
    const cite = { marker: 1, chunk_id: 'k1', doc_id: 'd1', doc_title: doc.title, location_label: 'page 1, para 1', page: 1, bboxes: [[72, 62, 400, 92]], snippet: 'We evaluate on the FloraBench dataset of leaf disease images, with 18,000 annotated photographs', highlight_span: null, score: 0.9, cited: true }
    ev('retrieval', { message_id: id, chunks: 1 }); await sleep(500); ev('citations', [cite])
    const text = 'The study used the **FloraBench** dataset of leaf disease images, with 18,000 annotated photographs [1].'
    for (const w of text.split(/(?<= )/)) { ev('token', { text: w }); await sleep(45) }
    const conf = { level: 'high', score: 0.82 }; ev('confidence', conf); ev('done', { message_id: id, latency_ms: 2100 })
    const mk = (role, content, extra = {}) => ({ id: role + id, role, content, created_at: new Date().toISOString(), mode: null, model: null, refused: false, confidence: null, citations: [], faithfulness: null, tokens: null, latency_ms: null, ...extra })
    msgs[mm[1]].push(mk('user', b.question), { ...mk('assistant', text, { confidence: conf, citations: [cite], latency_ms: 2100 }), id })
    return res.end()
  }
  return json(res, { error: { code: 'not_found', message: p, retryable: false } }, 404)
}).listen(8000, () => console.log('mock on 8000'))
