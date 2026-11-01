// Typed client for the PaperWise backend (API contract, Section 12 of the spec).
// All paths go through /api/v1; the Vite dev server proxies them to the backend.

export const BASE = '/api/v1'

export type DocStatus = 'queued' | 'extracting' | 'ocr' | 'indexing' | 'enriching' | 'ready' | 'failed'

export interface Doc {
  id: string
  filename: string
  file_type: string
  status: DocStatus
  page_count: number | null
  title: string | null
  authors: string[]
  added_at: string
  warnings: string[]
  intelligence_badge: { age_bucket: string | null; evidence_level: string | null } | null
}

export interface Citation {
  marker: number
  chunk_id: string | null
  doc_id: string | null
  doc_title: string | null
  location_label: string | null
  page: number | null
  bboxes: number[][] | null
  snippet: string | null
  highlight_span: { start: number; end: number } | null
  score: number | null
  cited: boolean
}

export type Level = 'high' | 'medium' | 'low'
export interface Confidence {
  level: Level
  score: number
}
export interface FaithSentence {
  start: number
  end: number
  label: 'supported' | 'partial' | 'unsupported'
  chunk_ids: string[]
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  mode: string | null
  model: string | null
  refused: boolean
  confidence: Confidence | null
  citations: Citation[]
  faithfulness: FaithSentence[] | null
  tokens: number | null
  latency_ms: number | null
}

export interface Chat {
  id: string
  title: string | null
  summary: string | null
  updated_at: string
  doc_ids: string[]
  pinned: boolean
  topic_id: string | null
  model: string | null
}
export interface ChatWithMessages extends Chat {
  messages: Message[]
}

export interface ModelInfo {
  name: string
  size_gb: number
  family: string | null
  params: string | null
  quant: string | null
}

export interface Health {
  status: string
  version: string
  ollama: { up: boolean; models: string[] }
  internet: boolean
  online_lookups_enabled: boolean
  device: string
}

export interface Settings {
  default_model: string
  top_k: number
  hybrid_weights: { semantic: number; bm25: number }
  use_reranker: boolean
  num_ctx: number
  online_lookups: boolean
  similarity_weights: { topic: number; docs: number }
  notes_in_retrieval: boolean
}

export interface RetrievedChunk {
  chunk_id: string
  doc_id: string
  location_label: string
  hybrid_score: number | null
  rerank_score: number | null
  cosine: number | null
  rank: number
  text: string
}
export interface DebugInfo {
  expanded_query: string | null
  retrieved: RetrievedChunk[]
  final_prompt: { role: string; content: string }[] | string | null
  context_trimmed: boolean
  warnings: string[]
  timings_ms: Record<string, number>
}

export class ApiError extends Error {
  code: string
  status: number
  hint?: string
  retryable: boolean
  constructor(message: string, code: string, status: number, hint?: string, retryable = false) {
    super(message)
    this.code = code
    this.status = status
    this.hint = hint
    this.retryable = retryable
  }
}

async function toError(res: Response): Promise<ApiError> {
  try {
    const j = await res.json()
    const e = j.error
    if (e) return new ApiError(e.message ?? res.statusText, e.code ?? 'INTERNAL', res.status, e.hint, !!e.retryable)
    if (j.detail) return new ApiError(typeof j.detail === 'string' ? j.detail : 'The request was not valid.', 'VALIDATION_ERROR', res.status)
  } catch {
    /* not JSON */
  }
  return new ApiError(res.statusText || 'Request failed', 'INTERNAL', res.status)
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(BASE + path, init)
  } catch {
    throw new ApiError('Cannot reach the PaperWise backend.', 'BACKEND_UNREACHABLE', 0, 'Start it with make run in the paperwise folder.', true)
  }
  if (!res.ok) throw await toError(res)
  return res.json() as Promise<T>
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  health: () => req<Health>('/health'),
  models: () => req<ModelInfo[]>('/models'),
  settings: () => req<Settings>('/settings'),
  updateSettings: (patch: Partial<Settings>) => req<Settings>('/settings', json('PUT', patch)),

  documents: () => req<Doc[]>('/documents'),
  uploadDocuments: (files: File[]) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return req<{ doc_id: string; filename: string; status: DocStatus; warning?: string }[]>('/documents', { method: 'POST', body: form })
  },
  deleteDocument: (id: string) => req<{ ok: boolean }>(`/documents/${id}`, { method: 'DELETE' }),
  fileUrl: (id: string) => `${BASE}/documents/${id}/file`,
  chunk: (docId: string, chunkId: string) =>
    req<{ chunk_id: string; text: string; location_label: string; page: number | null }>(
      `/documents/${docId}/chunks/${encodeURIComponent(chunkId)}`,
    ),

  chats: () => req<Chat[]>('/chats'),
  chat: (id: string) => req<ChatWithMessages>(`/chats/${id}`),
  createChat: (doc_ids: string[]) => req<Chat>('/chats', json('POST', { doc_ids })),
  patchChat: (id: string, patch: Partial<Pick<Chat, 'title' | 'pinned' | 'doc_ids' | 'model'>>) =>
    req<Chat>(`/chats/${id}`, json('PATCH', patch)),
  deleteChat: (id: string) => req<{ ok: boolean }>(`/chats/${id}`, { method: 'DELETE' }),
  exportUrl: (id: string) => `${BASE}/chats/${id}/export?format=md`,
  debug: (chatId: string, mid: string) => req<DebugInfo>(`/chats/${chatId}/messages/${mid}/debug`),
  stop: (chatId: string, mid: string) => req<{ stopped: boolean }>(`/chats/${chatId}/messages/${mid}/stop`, { method: 'POST' }),
}

export interface SendBody {
  question: string
  doc_ids?: string[]
  top_k?: number
  mode?: 'auto' | 'qa' | 'compare'
  model?: string | null
}

/** Sends a question and reads the Server-Sent Events stream (Section 12.4). */
export async function streamMessage(
  chatId: string,
  body: SendBody,
  onEvent: (event: string, data: unknown) => void,
  signal: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${BASE}/chats/${chatId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError('Cannot reach the PaperWise backend.', 'BACKEND_UNREACHABLE', 0, 'Start it with make run in the paperwise folder.', true)
  }
  if (!res.ok) throw await toError(res)
  if (!res.body) throw new ApiError('The server sent no stream.', 'INTERNAL', 500)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const flush = (block: string) => {
    let event = 'message'
    const data: string[] = []
    for (const line of block.split('\n')) {
      if (!line || line.startsWith(':')) continue
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
    }
    if (!data.length) return
    try {
      onEvent(event, JSON.parse(data.join('\n')))
    } catch {
      /* ignore a malformed event */
    }
  }
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let i: number
    while ((i = buffer.indexOf('\n\n')) >= 0) {
      flush(buffer.slice(0, i))
      buffer = buffer.slice(i + 2)
    }
  }
  if (buffer.trim()) flush(buffer)
}

/** Subscribes to ingestion progress. Returns a function that closes the stream. */
export function watchDocuments(
  onProgress: (p: { doc_id: string; status: DocStatus; percent?: number; message?: string }) => void,
): () => void {
  const es = new EventSource(`${BASE}/documents/events`)
  es.addEventListener('progress', (e) => {
    try {
      onProgress(JSON.parse((e as MessageEvent).data))
    } catch {
      /* ignore */
    }
  })
  return () => es.close()
}
