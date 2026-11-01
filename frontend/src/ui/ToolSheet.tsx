import { useEffect } from 'react'
import { TOOLS } from '../tools'
import { useStore } from '../store'
import { Ask } from './Ask'
import { Library } from './Library'
import { Reader } from './Reader'
import { Settings } from './Settings'

export function ToolSheet() {
  const tool = useStore((s) => s.tool)
  const set = useStore((s) => s.set)
  const close = () => set({ tool: null })
  useEffect(() => {
    if (!tool) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && close()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [tool])
  if (!tool) return null
  const meta = TOOLS.find((t) => t.id === tool)
  const title = tool === 'settings' ? 'Settings' : meta!.title
  return (
    <div className="scrim fixed inset-0 z-40 flex items-center justify-center p-3 sm:p-8" data-ui style={{ background: 'rgba(30,20,8,0.38)' }} onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <section role="dialog" aria-modal="true" aria-label={title} className="sheet flex h-full max-h-[880px] w-full max-w-[1100px] flex-col p-5 sm:p-8">
        <header className="mb-4 flex items-start gap-3 border-b border-rule pb-3">
          <div className="flex-1">
            <h2 className="m-0 font-display text-[34px] font-bold leading-none">{title}</h2>
            {meta && <p className="mt-1 text-ink-2">{meta.blurb}</p>}
          </div>
          <button className="btn btn-quiet" onClick={close} aria-label="Close">Close</button>
        </header>
        <div className="min-h-0 flex-1">
          {tool === 'ask' && <Ask />}
          {tool === 'library' && <Library />}
          {tool === 'reader' && <Reader />}
          {tool === 'settings' && <Settings />}
          {meta && !meta.ready && (
            <div className="mx-auto mt-16 max-w-md text-center">
              <p className="font-display text-[26px] font-semibold">Wired up next</p>
              <p className="mt-2 text-ink-2">{meta.detail}</p>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
