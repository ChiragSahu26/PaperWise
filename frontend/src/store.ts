import { create } from 'zustand'
import {
  api,
  ApiError,
  streamMessage,
  type Chat,
  type Citation,
  type Confidence,
  type Doc,
  type DocStatus,
  type FaithSentence,
  type Health,
  type Message,
  type ModelInfo,
  type Settings,
} from './api'
import type { ToolId } from './tools'

export interface Live {
  question: string
  id: string | null
  content: string
  citations: Citation[]
  confidence: Confidence | null
  phase: 'retrieving' | 'generating' | 'done' | 'error'
  refused: boolean
  faithfulness: FaithSentence[] | null
  error: { code: string; message: string; hint?: string } | null
  model: string | null
  latency_ms: number | null
}

export type Panel =
  | { kind: 'closed' }
  | { kind: 'sources'; messageId: string; marker?: number }
  | { kind: 'debug'; messageId: string }
  | { kind: 'pdf'; docId: string; title: string; page: number; boxes: number[][] | null; back?: { messageId: string; marker?: number } }

export type AskMode = 'auto' | 'qa' | 'compare'

interface State {
  docs: Doc[]
  progress: Record<string, number>
  chats: Chat[]
  messages: Message[]
  live: Live | null
  activeChatId: string | null
  draftDocIds: string[]
  settings: Settings | null
  health: Health | null
  healthError: boolean
  models: ModelInfo[]
  panel: Panel
  tool: ToolId | 'settings' | null
  theme: 'light' | 'dark'
  reader: { docId: string; title: string; page: number; boxes: number[][] | null } | null
  mode: AskMode
  model: string | null
  settingsOpen: boolean
  sidebarOpen: boolean
  notice: string | null

  init: () => Promise<void>
  refreshDocs: () => Promise<void>
  refreshChats: () => Promise<void>
  refreshHealth: () => Promise<void>
  applyProgress: (p: { doc_id: string; status: DocStatus; percent?: number }) => void
  selectChat: (id: string | null) => Promise<void>
  toggleDoc: (id: string) => Promise<void>
  upload: (files: File[]) => Promise<void>
  removeDoc: (id: string) => Promise<void>
  removeChat: (id: string) => Promise<void>
  renameChat: (id: string, title: string) => Promise<void>
  togglePin: (id: string) => Promise<void>
  send: (question: string) => Promise<void>
  stop: () => Promise<void>
  saveSettings: (patch: Partial<Settings>) => Promise<void>
  setPanel: (p: Panel) => void
  set: (p: Partial<State>) => void
}

let abortCtl: AbortController | null = null

export const selectedIds = (s: Pick<State, 'chats' | 'activeChatId' | 'draftDocIds'>): string[] => {
  const chat = s.chats.find((c) => c.id === s.activeChatId)
  return chat ? chat.doc_ids : s.draftDocIds
}

export const useStore = create<State>((set, get) => ({
  docs: [],
  progress: {},
  chats: [],
  messages: [],
  live: null,
  activeChatId: null,
  draftDocIds: [],
  settings: null,
  health: null,
  healthError: false,
  models: [],
  panel: { kind: 'closed' },
  tool: null,
  theme: (typeof localStorage !== 'undefined' && localStorage.getItem('pw-theme') === 'dark') ? 'dark' : 'light',
  reader: null,
  mode: 'auto',
  model: null,
  settingsOpen: false,
  sidebarOpen: false,
  notice: null,

  set: (p) => set(p),
  setPanel: (panel) => set({ panel }),

  init: async () => {
    await Promise.all([get().refreshHealth(), get().refreshDocs(), get().refreshChats()])
    api.settings().then((settings) => set({ settings })).catch(() => {})
    api.models().then((models) => set({ models })).catch(() => set({ models: [] }))
  },

  refreshDocs: async () => {
    try {
      set({ docs: await api.documents() })
    } catch {
      /* the health banner explains an unreachable backend */
    }
  },
  refreshChats: async () => {
    try {
      set({ chats: await api.chats() })
    } catch {
      /* ignore */
    }
  },
  refreshHealth: async () => {
    try {
      const health = await api.health()
      set({ health, healthError: false })
      if (health.ollama.up && get().models.length === 0) api.models().then((models) => set({ models })).catch(() => {})
    } catch {
      set({ healthError: true })
    }
  },

  applyProgress: ({ doc_id, status, percent }) => {
    set((s) => ({
      docs: s.docs.map((d) => (d.id === doc_id ? { ...d, status } : d)),
      progress: { ...s.progress, [doc_id]: percent ?? s.progress[doc_id] ?? 0 },
    }))
    if (status === 'ready' || status === 'failed') get().refreshDocs()
  },

  selectChat: async (id) => {
    abortCtl?.abort()
    set({ activeChatId: id, messages: [], live: null, panel: { kind: 'closed' }, sidebarOpen: false })
    if (!id) return
    try {
      const chat = await api.chat(id)
      if (get().activeChatId === id) set({ messages: chat.messages })
    } catch {
      set({ notice: 'That chat could not be opened.' })
    }
  },

  toggleDoc: async (docId) => {
    const s = get()
    const ids = selectedIds(s)
    const next = ids.includes(docId) ? ids.filter((x) => x !== docId) : [...ids, docId]
    if (!s.activeChatId) return set({ draftDocIds: next })
    set({ chats: s.chats.map((c) => (c.id === s.activeChatId ? { ...c, doc_ids: next } : c)) })
    try {
      await api.patchChat(s.activeChatId, { doc_ids: next })
    } catch {
      get().refreshChats()
    }
  },

  upload: async (files) => {
    if (!files.length) return
    try {
      const results = await api.uploadDocuments(files)
      const ids = results.map((r) => r.doc_id)
      const s = get()
      if (s.activeChatId) {
        const current = selectedIds(s)
        const next = [...new Set([...current, ...ids])]
        set({ chats: s.chats.map((c) => (c.id === s.activeChatId ? { ...c, doc_ids: next } : c)) })
        api.patchChat(s.activeChatId, { doc_ids: next }).catch(() => get().refreshChats())
      } else {
        set({ draftDocIds: [...new Set([...s.draftDocIds, ...ids])] })
      }
      const warned = results.find((r) => r.warning)
      if (warned) set({ notice: warned.warning ?? null })
      await get().refreshDocs()
    } catch (e) {
      set({ notice: e instanceof ApiError ? `${e.message}${e.hint ? ' ' + e.hint : ''}` : 'Upload failed.' })
    }
  },

  removeDoc: async (id) => {
    try {
      await api.deleteDocument(id)
      set((s) => ({ draftDocIds: s.draftDocIds.filter((x) => x !== id) }))
      await Promise.all([get().refreshDocs(), get().refreshChats()])
    } catch (e) {
      set({ notice: e instanceof ApiError ? e.message : 'The document could not be removed.' })
    }
  },

  removeChat: async (id) => {
    try {
      await api.deleteChat(id)
      if (get().activeChatId === id) await get().selectChat(null)
      await get().refreshChats()
    } catch {
      set({ notice: 'The chat could not be deleted.' })
    }
  },
  renameChat: async (id, title) => {
    const clean = title.trim()
    if (!clean) return
    set((s) => ({ chats: s.chats.map((c) => (c.id === id ? { ...c, title: clean } : c)) }))
    try {
      await api.patchChat(id, { title: clean })
    } catch {
      get().refreshChats()
    }
  },
  togglePin: async (id) => {
    const chat = get().chats.find((c) => c.id === id)
    if (!chat) return
    set((s) => ({ chats: s.chats.map((c) => (c.id === id ? { ...c, pinned: !c.pinned } : c)) }))
    try {
      await api.patchChat(id, { pinned: !chat.pinned })
    } catch {
      get().refreshChats()
    }
  },

  saveSettings: async (patch) => {
    try {
      const settings = await api.updateSettings(patch)
      set({ settings })
      get().refreshHealth()
    } catch (e) {
      set({ notice: e instanceof ApiError ? e.message : 'Settings were not saved.' })
    }
  },

  send: async (question) => {
    const start = get()
    if (start.live && (start.live.phase === 'retrieving' || start.live.phase === 'generating')) return
    const ids = selectedIds(start)
    if (!ids.length || !question.trim()) return

    const live: Live = {
      question, id: null, content: '', citations: [], confidence: null, phase: 'retrieving',
      refused: false, faithfulness: null, error: null, model: null, latency_ms: null,
    }
    const patch = (p: Partial<Live> | ((l: Live) => Partial<Live>)) =>
      set((s) => (s.live ? { live: { ...s.live, ...(typeof p === 'function' ? p(s.live) : p) } } : {}))

    let chatId = start.activeChatId
    try {
      if (!chatId) {
        const chat = await api.createChat(ids)
        chatId = chat.id
        set((s) => ({ activeChatId: chat.id, chats: [chat, ...s.chats], draftDocIds: [] }))
      }
    } catch (e) {
      set({ notice: e instanceof ApiError ? `${e.message} ${e.hint ?? ''}` : 'The chat could not be started.' })
      return
    }

    const userMessage: Message = {
      id: 'pending-user', role: 'user', content: question, created_at: new Date().toISOString(),
      mode: null, model: null, refused: false, confidence: null, citations: [], faithfulness: null, tokens: null, latency_ms: null,
    }
    set((s) => ({ messages: [...s.messages, userMessage], live }))

    abortCtl = new AbortController()
    const body = { question, mode: start.mode, model: start.model ?? undefined, top_k: undefined as number | undefined }
    try {
      await streamMessage(chatId, body, (event, raw) => {
        const d = raw as any // eslint-disable-line @typescript-eslint/no-explicit-any
        if (event === 'retrieval') patch({ id: d.message_id, phase: 'generating' })
        else if (event === 'citations') patch({ citations: d })
        else if (event === 'token') patch((l) => ({ content: l.content + d.text }))
        else if (event === 'confidence') patch({ confidence: d })
        else if (event === 'done') patch({ phase: 'done', refused: !!d.refused, model: d.model, latency_ms: d.latency_ms })
        else if (event === 'faithfulness') patch({ faithfulness: d.sentences })
        else if (event === 'error') patch({ phase: 'error', error: { code: d.code, message: d.message } })
      }, abortCtl.signal)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        const err = e instanceof ApiError ? e : new ApiError('The answer could not be completed.', 'INTERNAL', 0)
        patch({ phase: 'error', error: { code: err.code, message: err.message, hint: err.hint } })
      }
    }

    // Sync with what the server saved. Keep an error visible if nothing was stored.
    const finished = get().live
    if (get().activeChatId !== chatId) return
    try {
      const saved = await api.chat(chatId)
      const assistant = [...saved.messages].reverse().find((m) => m.role === 'assistant')
      if (finished?.faithfulness && assistant && assistant.id === finished.id && !assistant.faithfulness) {
        assistant.faithfulness = finished.faithfulness
      }
      const failedWithoutAnswer = finished?.phase === 'error' && !(assistant && assistant.content)
      set({ messages: saved.messages, live: failedWithoutAnswer ? finished : null })
    } catch {
      /* keep the live message on screen */
    }
    get().refreshChats()
    setTimeout(() => get().refreshChats(), 4000)
    setTimeout(() => get().refreshChats(), 10000)
  },

  stop: async () => {
    const { live, activeChatId } = get()
    if (!live) return
    if (live.id && activeChatId) {
      try {
        await api.stop(activeChatId, live.id)
        return
      } catch {
        /* fall through to aborting the request */
      }
    }
    abortCtl?.abort()
    set({ live: null })
    if (activeChatId) get().selectChat(activeChatId)
  },
}))
