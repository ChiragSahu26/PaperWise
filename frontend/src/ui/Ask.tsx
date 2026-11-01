import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { selectedIds, useStore } from '../store'
import type { Citation, Message } from '../api'
import { PdfViewer } from './PdfViewer'

const CONF = { high: ['Well supported', 'text-green bg-green-soft'], medium: ['Partly supported', 'text-amber bg-amber-soft'], low: ['Weak evidence', 'text-red bg-red-soft'] } as const

function Answer({ text, cites, onCite, streaming }: { text: string; cites: Citation[]; onCite: (c: Citation) => void; streaming?: boolean }) {
  const md = useMemo(() => text.replace(/\[(\d+)\]/g, (_, n) => `[${n}](#cite-${n})`), [text])
  return (
    <div className={`prose-answer ${streaming ? 'caret' : ''}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            const m = /^#cite-(\d+)$/.exec(href ?? '')
            if (!m) return <a href={href} target="_blank" rel="noreferrer" className="text-blue underline">{children}</a>
            const c = cites.find((x) => x.marker === +m[1])
            return <button className="cite" disabled={!c} onClick={() => c && onCite(c)} title={c?.doc_title ?? ''}>{m[1]}</button>
          },
          table: ({ children }) => <div className="table-wrap"><table>{children}</table></div>,
        }}
      >
        {md}
      </ReactMarkdown>
    </div>
  )
}

function Bubble({ m, onCite }: { m: Message; onCite: (c: Citation) => void }) {
  if (m.role === 'user') return <p className="ml-auto w-fit max-w-[80%] bg-paper-2 px-3.5 py-2 font-display text-[19px] font-medium">{m.content}</p>
  const conf = m.confidence ? CONF[m.confidence.level] : null
  const bad = m.faithfulness?.filter((f) => f.label === 'unsupported').length ?? 0
  return (
    <div>
      <Answer text={m.content} cites={m.citations} onCite={onCite} />
      <div className="mt-2 flex flex-wrap items-center gap-2 font-display text-[15px]">
        {m.refused && <span className="bg-amber-soft px-2 text-amber">Not in your papers</span>}
        {conf && !m.refused && <span className={`px-2 ${conf[1]}`}>{conf[0]}</span>}
        {bad > 0 && <span className="bg-red-soft px-2 text-red">{bad} sentence{bad > 1 ? 's' : ''} not backed by the sources</span>}
        {m.latency_ms != null && <span className="text-ink-3">{(m.latency_ms / 1000).toFixed(1)}s</span>}
      </div>
    </div>
  )
}

export function Ask() {
  const s = useStore()
  const ids = selectedIds(s)
  const [q, setQ] = useState('')
  const [side, setSide] = useState<{ c: Citation; page: number } | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const ready = s.docs.filter((d) => d.status === 'ready')
  const busy = s.live != null && s.live.phase !== 'done' && s.live.phase !== 'error'

  // A new question starts with every ready paper selected; the chips narrow it down.
  useEffect(() => {
    if (!s.activeChatId && s.draftDocIds.length === 0 && ready.length) s.set({ draftDocIds: ready.map((d) => d.id) })
  }, [s.activeChatId, ready.length])

  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [s.messages.length, s.live?.content])

  const submit = () => {
    const t = q.trim()
    if (!t || busy) return
    setQ('')
    void s.send(t)
  }
  const open = (c: Citation) => setSide({ c, page: c.page ?? 1 })

  return (
    <div className="flex h-full min-h-0 gap-5">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          {ready.length === 0 && <span className="text-ink-3 text-[15px]">Add a paper first, then ask about it.</span>}
          {ready.map((d) => {
            const on = ids.includes(d.id)
            return (
              <button key={d.id} onClick={() => s.toggleDoc(d.id)} aria-pressed={on} className={`max-w-[16rem] truncate border px-2.5 py-0.5 text-[16px] font-medium ${on ? 'border-ink bg-ink text-paper' : 'border-rule text-ink-2'}`}>
                {d.title || d.filename}
              </button>
            )
          })}
          <select className="field ml-auto !py-0.5" value={s.mode} onChange={(e) => s.set({ mode: e.target.value as 'auto' | 'qa' | 'compare' })} aria-label="Mode">
            <option value="auto">Auto</option>
            <option value="qa">Single paper</option>
            <option value="compare">Compare papers</option>
          </select>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-auto pr-1">
          {s.messages.length === 0 && !s.live && (
            <p className="py-10 text-center text-ink-3">Ask something your papers can answer. For example: <em>What dataset was used?</em></p>
          )}
          {s.messages.filter((m) => !(s.live && m.id === s.live.id)).map((m) => <Bubble key={m.id} m={m} onCite={open} />)}
          {s.live && s.live.phase !== 'done' && (
            <div>
              {s.live.phase === 'retrieving' && <p className="text-ink-3 font-display text-[17px]">Searching your papers…</p>}
              {s.live.content && <Answer text={s.live.content} cites={s.live.citations} onCite={open} streaming={s.live.phase === 'generating'} />}
              {s.live.error && <p className="bg-red-soft px-3 py-2 text-red">{s.live.error.message}{s.live.error.hint ? ` ${s.live.error.hint}` : ''}</p>}
            </div>
          )}
          <div ref={end} />
        </div>

        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); submit() }}>
          <textarea
            className="field min-h-[44px] flex-1 resize-none"
            rows={1}
            value={q}
            placeholder="Ask about your papers"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
          />
          {busy ? <button type="button" className="btn btn-quiet" onClick={() => s.stop()}>Stop</button> : <button className="btn" disabled={!q.trim() || ids.length === 0} title={ids.length === 0 ? 'Select at least one paper' : undefined}>Ask</button>}
        </form>
      </div>

      {side && (
        <aside className="hidden min-h-0 w-[42%] shrink-0 flex-col md:flex">
          <div className="mb-2 flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <p className="truncate font-display text-[18px] font-semibold leading-tight">{side.c.doc_title}</p>
              <p className="text-[14px] text-ink-3">{side.c.location_label}</p>
            </div>
            <button className="btn btn-quiet !py-0.5" onClick={() => setSide(null)} aria-label="Close source">✕</button>
          </div>
          {side.c.doc_id && side.c.page ? (
            <PdfViewer docId={side.c.doc_id} page={side.page} boxes={side.page === side.c.page ? side.c.bboxes : null} onPage={(p) => setSide({ ...side, page: p })} />
          ) : (
            <p className="border border-rule bg-paper-2 p-3 text-[15px]">{side.c.snippet}</p>
          )}
        </aside>
      )}
    </div>
  )
}
