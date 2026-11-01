import { useEffect, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { api } from '../api'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

/** One PDF page with the cited passage marked. Boxes are [x0, y0, x1, y1] in PDF points. */
export function PdfViewer({ docId, page, boxes, onPage }: { docId: string; page: number; boxes: number[][] | null; onPage?: (p: number) => void }) {
  const wrap = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [doc, setDoc] = useState<pdfjs.PDFDocumentProxy | null>(null)
  const [scale, setScale] = useState(1)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let dead = false
    setDoc(null)
    setErr(null)
    const task = pdfjs.getDocument({ url: api.fileUrl(docId) })
    task.promise.then((d) => !dead && setDoc(d), () => !dead && setErr('This file could not be opened as a PDF.'))
    return () => {
      dead = true
      task.destroy()
    }
  }, [docId])

  const job = useRef<pdfjs.RenderTask | null>(null)
  useEffect(() => {
    if (!doc || !canvas.current || !wrap.current) return
    let dead = false
    const n = Math.min(Math.max(1, page), doc.numPages)
    ;(async () => {
      const pg = await doc.getPage(n)
      if (dead) return
      // a canvas can only run one render at a time: finish cancelling the previous one first
      const prev = job.current
      if (prev) {
        prev.cancel()
        await prev.promise.catch(() => {})
        if (dead) return
      }
      const base = pg.getViewport({ scale: 1 })
      const sc = Math.max(280, wrap.current!.clientWidth - 2) / base.width
      const vp = pg.getViewport({ scale: sc * (window.devicePixelRatio || 1) })
      const c = canvas.current!
      c.width = vp.width
      c.height = vp.height
      c.style.width = `${base.width * sc}px`
      c.style.height = `${base.height * sc}px`
      setScale(sc)
      setSize({ w: base.width * sc, h: base.height * sc })
      const task = pg.render({ canvas: c, viewport: vp })
      job.current = task
      try {
        await task.promise
      } catch (e) {
        if ((e as Error)?.name !== 'RenderingCancelledException') setErr('The page could not be drawn.')
      }
    })()
    return () => {
      dead = true
    }
  }, [doc, page])

  useEffect(() => {
    if (size.h && boxes?.length && wrap.current) {
      const top = Math.min(...boxes.map((b) => b[1])) * scale
      wrap.current.scrollTo({ top: Math.max(0, top - 80), behavior: 'smooth' })
    }
  }, [boxes, size.h, scale])

  const n = doc?.numPages ?? 0
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-2 flex items-center gap-2 font-display text-[17px]">
        <button className="btn btn-quiet !px-2.5 !py-0.5" disabled={page <= 1} onClick={() => onPage?.(page - 1)} aria-label="Previous page">‹</button>
        <span className="text-ink-2">Page {page}{n ? ` of ${n}` : ''}</span>
        <button className="btn btn-quiet !px-2.5 !py-0.5" disabled={!n || page >= n} onClick={() => onPage?.(page + 1)} aria-label="Next page">›</button>
      </div>
      <div ref={wrap} className="relative min-h-0 flex-1 overflow-auto border border-rule bg-paper-2">
        {err && <p className="p-4 text-red">{err}</p>}
        <div className="relative" style={{ width: size.w || undefined, height: size.h || undefined }}>
          <canvas ref={canvas} className="block" />
          {boxes?.map((b, i) => (
            <div
              key={i}
              className="pointer-events-none absolute rounded-[2px]"
              style={{ left: b[0] * scale, top: b[1] * scale, width: (b[2] - b[0]) * scale, height: (b[3] - b[1]) * scale, background: 'rgba(255, 214, 10, 0.42)', mixBlendMode: 'multiply' }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
