import { useStore } from '../store'

export function Settings() {
  const { settings, models, health, saveSettings } = useStore()
  if (!settings) return <p className="text-ink-3">Settings are not available while the backend is offline.</p>
  return (
    <div className="space-y-5 max-w-xl">
      <label className="block">
        <span className="font-display text-[19px] font-semibold">Local model</span>
        <select className="field mt-1 block w-full" value={settings.default_model} onChange={(e) => saveSettings({ default_model: e.target.value })}>
          {models.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
        </select>
      </label>
      <label className="block">
        <span className="font-display text-[19px] font-semibold">Passages per answer: {settings.top_k}</span>
        <input type="range" min={2} max={12} value={settings.top_k} className="block w-full" onChange={(e) => saveSettings({ top_k: +e.target.value })} />
      </label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={settings.use_reranker} onChange={(e) => saveSettings({ use_reranker: e.target.checked })} /> <span className="font-display text-[19px] font-semibold">Re-rank passages (slower, more accurate)</span></label>
      <p className="text-[14px] text-ink-3">Backend: {health?.status ?? 'unknown'} · Ollama {health?.ollama?.up ? 'running' : 'not running'}</p>
    </div>
  )
}
