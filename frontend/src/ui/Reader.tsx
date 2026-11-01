import { useStore } from '../store'
import { PdfViewer } from './PdfViewer'

export function Reader() {
  const docs = useStore((s) => s.docs).filter((d) => d.status === 'ready' && d.file_type === 'pdf')
  const r = useStore((s) => s.reader)
  const set = useStore((s) => s.set)
  if (!r)
    return (
      <div>
        <p className="mb-3 text-ink-2">Choose a paper to read.</p>
        <ul className="divide-y divide-rule border-y border-rule">
          {docs.length === 0 && <li className="py-6 text-center text-ink-3">No PDFs yet.</li>}
          {docs.map((d) => (
            <li key={d.id}><button className="w-full py-2.5 text-left font-display text-[20px] font-semibold hover:text-blue" onClick={() => set({ reader: { docId: d.id, title: d.title || d.filename, page: 1, boxes: null } })}>{d.title || d.filename}</button></li>
          ))}
        </ul>
      </div>
    )
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-2 flex items-center gap-2"><button className="btn btn-quiet !py-0.5" onClick={() => set({ reader: null })}>‹ Papers</button><p className="truncate font-display text-[19px] font-semibold">{r.title}</p></div>
      <PdfViewer docId={r.docId} page={r.page} boxes={r.boxes} onPage={(page) => set({ reader: { ...r, page, boxes: null } })} />
    </div>
  )
}
