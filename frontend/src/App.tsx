import { useEffect, useRef, useState } from 'react'
import { PaperScene } from './scene/PaperScene'
import { TOOLS } from './tools'
import { useStore } from './store'
import { ToolSheet } from './ui/ToolSheet'

export default function App() {
  const canvas = useRef<HTMLCanvasElement>(null)
  const scene = useRef<PaperScene | null>(null)
  const [hover, setHover] = useState<number | null>(null)
  const [final, setFinal] = useState(false)
  const [webgl, setWebgl] = useState(true)
  const { theme, tool, health, healthError, set, init } = useStore()

  useEffect(() => { void init() }, [init])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('pw-theme', theme) } catch { /* private mode */ }
    scene.current?.setTheme(theme === 'dark')
  }, [theme])

  useEffect(() => {
    let dead = false
    let off = () => {}
    PaperScene.create(canvas.current!, TOOLS, { onHover: setHover, onPick: (i) => set({ tool: TOOLS[i].id }) }, useStore.getState().theme === 'dark')
      .then((s) => {
        if (dead) return s.dispose()
        scene.current = s
        ;(window as any).__scene = s
        const onScroll = () => {
          const max = document.documentElement.scrollHeight - window.innerHeight
          const p = max > 0 ? window.scrollY / max : 0
          s.setProgress(p)
          setFinal(p > 0.94)
        }
        window.addEventListener('scroll', onScroll, { passive: true })
        onScroll()
        off = () => window.removeEventListener('scroll', onScroll)
      })
      .catch(() => !dead && setWebgl(false))
    return () => { dead = true; off(); scene.current?.dispose(); scene.current = null }
  }, [set])

  useEffect(() => { scene.current?.setEnabled(!tool) }, [tool])

  const skip = () => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' })
  const online = !healthError && health?.status != null

  return (
    <>
      <canvas id="stage" ref={canvas} aria-hidden="true" />
      <div style={{ height: '700vh' }} aria-hidden="true" />

      <header className="chrome fixed left-0 right-0 top-0 z-30 flex items-center gap-3 px-5 py-2.5" data-ui style={{ borderWidth: '0 0 1px 0' }}>
        <span className="font-display text-[24px] font-bold tracking-tight">PaperWise</span>
        <span className="hidden font-display text-[16px] text-chrome-2 sm:inline">
          <span className={`mr-1.5 inline-block h-2 w-2 rounded-full ${online ? 'bg-[#2e9e6b]' : 'bg-[#c4453c]'}`} />
          {online ? (health?.ollama?.up ? 'Local model ready' : 'Ollama not running') : 'Backend offline'}
        </span>
        <span className="flex-1" />
        {!final && <button className="font-display text-[17px] underline underline-offset-4" onClick={skip}>Skip intro</button>}
        <button className="font-display text-[17px]" onClick={() => set({ tool: 'settings' })}>Settings</button>
        <button className="font-display text-[17px]" aria-label="Toggle dark mode" aria-pressed={theme === 'dark'} onClick={() => set({ theme: theme === 'dark' ? 'light' : 'dark' })}>
          {theme === 'dark' ? 'Light' : 'Dark'}
        </button>
      </header>

      {!final && (
        <p className="chrome-text fixed bottom-7 left-0 right-0 z-20 text-center font-display text-[18px] tracking-wide" style={{ color: 'var(--chrome-fg-2)' }}>
          Scroll to unfold <span className="drift inline-block">↓</span>
        </p>
      )}
      {final && (
        <p className="fixed bottom-6 left-0 right-0 z-20 text-center font-display text-[20px]" style={{ color: 'var(--chrome-fg)' }}>
          {hover != null ? TOOLS[hover].title : 'Pick a sheet'}
        </p>
      )}

      {/* Keyboard and screen-reader route to every tool */}
      <nav className="sr-only" aria-label="Tools">
        {TOOLS.map((t) => <button key={t.id} onClick={() => set({ tool: t.id })}>{t.title}</button>)}
      </nav>

      {!webgl && (
        <div className="fixed inset-0 z-10 flex flex-col items-center justify-center gap-3" data-ui>
          {TOOLS.map((t) => <button key={t.id} className="btn" onClick={() => set({ tool: t.id })}>{t.title}</button>)}
        </div>
      )}
      <ToolSheet />
    </>
  )
}
