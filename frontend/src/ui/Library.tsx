import { useRef, useState } from 'react'
import { useStore } from '../store'

const STATUS: Record<string, string> = { queued: 'Waiting', parsing: 'Reading', chunking: 'Splitting', embedding: 'Indexing', ready: 'Ready', failed: 'Failed' }

export function Library() {
  const docs = useStore((s) => s.docs)
  const progress = useStore((s) => s.progress)
  const upload = useStore((s) => s.upload)
  const removeDoc = useStore((s) => s.removeDoc)
  const set = useStore((s) => s.set)
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); upload([...e.dataTransfer.files]) }}
        className={`flex flex-col items-center gap-2 border-2 border-dashed px-6 py-8 text-center ${over ? 'border-blue bg-blue-soft' : 'border-rule'}`}
      >
        <p className="font-display text-[22px] font-semibold">Drop papers here</p>
        <p className="text-ink-2 text-[15px]">PDF, Word, slides, sheets, text or images</p>
        <button className="btn mt-1" onClick={() => input.current?.click()}>Choose files</button>
        <input ref={input} type="file" multiple hidden accept=".pdf,.docx,.pptx,.xlsx,.csv,.txt,.md,.png,.jpg,.jpeg" onChange={(e) => { upload([...(e.target.files ?? [])]); e.target.value = '' }} />
      </div>
      <ul className="min-h-0 flex-1 overflow-auto divide-y divide-rule border-y border-rule">
        {docs.length === 0 && <li className="py-6 text-center text-ink-3">No papers yet.</li>}
        {docs.map((d) => {
          const busy = d.status !== 'ready' && d.status !== 'failed'
          return (
            <li key={d.id} className="flex items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate font-display text-[19px] font-semibold leading-tight">{d.title || d.filename}</p>
                <p className="truncate text-[14px] text-ink-3">
                  {d.authors?.slice(0, 3).join(', ') || d.filename}
                  {d.page_count ? ` · ${d.page_count} pages` : ''}
                </p>
                {busy && <div className="mt-1 h-1 w-full bg-rule"><div className="h-1 bg-blue transition-all" style={{ width: `${progress[d.id] ?? 8}%` }} /></div>}
                {d.warnings?.length > 0 && <p className="text-[13px] text-amber">{d.warnings[0]}</p>}
              </div>
              <span className={`font-display text-[15px] ${d.status === 'failed' ? 'text-red' : d.status === 'ready' ? 'text-green' : 'text-amber'}`}>{STATUS[d.status] ?? d.status}</span>
              {d.status === 'ready' && d.file_type === 'pdf' && (
                <button className="btn btn-quiet !py-0.5" onClick={() => set({ reader: { docId: d.id, title: d.title || d.filename, page: 1, boxes: null }, tool: 'reader' })}>Read</button>
              )}
              <button className="btn btn-quiet !py-0.5" onClick={() => confirm(`Remove “${d.title || d.filename}”?`) && removeDoc(d.id)} aria-label={`Remove ${d.filename}`}>✕</button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
