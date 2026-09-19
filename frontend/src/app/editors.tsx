import { useEffect, useRef, useState } from 'react'
import { api, detectProvider, type Config, type ModelInfo, type Outline } from '../api'
import type { Profile } from './client'
import { Badge, Button, Field, Icon, Notice, Spinner, TextArea, TextInput } from './ui'

const TEMPLATE_NAMES: Record<string, string> = { jake: "Jake's Resume", 'awesome-cv': 'Awesome-CV', moderncv: 'moderncv', generic: 'Custom template' }

/** Paste or upload LaTeX, see what was recognized, and fix common problems. Reports whether it's usable. */
export function ResumeEditor({ tex, setTex, onValid }: { tex: string; setTex: (t: string) => void; onValid?: (ok: boolean) => void }) {
  const [parsed, setParsed] = useState<{ tex: string; outline: Outline | null; error: string | null } | null>(null)
  const [showOutline, setShowOutline] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!tex.trim()) return
    const t = setTimeout(() => {
      api
        .parse(tex)
        .then((o) => setParsed({ tex, outline: o, error: o.stats.sections === 0 ? 'No sections found. TailorTeX needs \\section{…} headings.' : null }))
        .catch((e: Error) => setParsed({ tex, outline: null, error: e.message }))
    }, 350)
    return () => clearTimeout(t)
  }, [tex])
  const current = tex.trim() && parsed?.tex === tex ? parsed : null
  const ok = !!current?.outline && !current.error && current.outline.stats.editable > 0
  useEffect(() => onValid?.(ok), [ok, onValid])

  const pasteClipboard = async () => {
    setMessage(null)
    try {
      const text = await navigator.clipboard.readText()
      if (!text.includes('\\')) return setMessage("What's on your clipboard doesn't look like LaTeX. Copy the code from Overleaf's editor, not the PDF preview.")
      setTex(text)
    } catch {
      setMessage('Your browser blocked clipboard access. Click in the box and press Ctrl/⌘ + V instead.')
    }
  }
  const upload = async (f: File | undefined) => {
    if (!f) return
    if (!/\.(tex|txt)$/i.test(f.name)) return setMessage('Pick the main .tex file of your resume.')
    if (f.size > 400_000) return setMessage('That file is larger than 400 KB.')
    setTex(await f.text())
  }

  return (
    <div className="flex flex-col gap-space-md">
      <ol className="list-decimal space-y-0.5 pl-5 font-body-sm text-body-sm text-on-surface-variant">
        <li>In Overleaf, click inside the editor (your main <code className="font-code-sm">.tex</code> file).</li>
        <li>Press Ctrl/⌘ A, then Ctrl/⌘ C.</li>
        <li>Paste it below, or use the button.</li>
      </ol>
      <TextArea
        value={tex}
        onChange={(e) => setTex(e.target.value)}
        rows={tex ? 12 : 7}
        spellCheck={false}
        aria-label="LaTeX source"
        placeholder={"Paste your resume's LaTeX, from \\documentclass to \\end{document}"}
        className="font-code-md text-code-md"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" onClick={pasteClipboard}><Icon name="content_paste" className="text-[18px]" /> Paste from clipboard</Button>
        <Button variant="ghost" size="sm" onClick={() => fileRef.current?.click()}><Icon name="upload_file" className="text-[18px]" /> Upload .tex</Button>
        {!tex.trim() && <Button variant="ghost" size="sm" onClick={async () => setTex((await api.template()).tex)}>Start from our template</Button>}
        <input ref={fileRef} type="file" accept=".tex,.txt" hidden onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = '' }} />
      </div>
      {message && <Notice tone="warn">{message}</Notice>}
      {tex.trim() && !current && <div className="flex items-center gap-2 font-body-sm text-body-sm text-on-surface-variant"><Spinner /> Reading your resume…</div>}
      {current?.error && <Notice tone="bad">{current.error}</Notice>}
      {current?.outline && !current.error && (
        <div className="rounded-xl bg-surface-container-low p-space-md">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="good"><Icon name="check_circle" fill className="text-[16px]" /> Recognized</Badge>
            <Badge>{TEMPLATE_NAMES[current.outline.profile] ?? current.outline.profile}</Badge>
            <span className="font-body-sm text-body-sm text-on-surface">{current.outline.stats.sections} sections · {current.outline.stats.bullets} bullets · {current.outline.stats.editable} editable</span>
            <button type="button" onClick={() => setShowOutline((s) => !s)} className="font-label-sm text-label-sm text-primary hover:underline">{showOutline ? 'Hide' : 'Show'} what we see</button>
          </div>
          {showOutline && (
            <div className="mt-3 max-h-72 overflow-auto rounded-lg bg-surface-container-lowest p-3 font-code-sm text-code-sm">
              {current.outline.sections.map((s) => (
                <div key={s.id} className="mb-2">
                  <div className="flex items-center gap-2 font-semibold text-on-surface">{s.title} {s.locked && <Badge className="font-normal"><Icon name="lock" className="text-[12px]" /> kept as is</Badge>}</div>
                  {s.blocks.map((b) => <div key={b.id} className="pl-3 text-on-surface-variant">{b.label ? `${b.label}: ` : ''}{b.text}</div>)}
                  {s.entries.map((e) => (
                    <div key={e.id} className="pl-3">
                      <div className="text-on-surface">{e.heading}</div>
                      {e.bullets.map((b) => <div key={b.id} className={`pl-3 ${b.locked ? 'text-outline' : 'text-on-surface-variant'}`}>• {b.text.replace(/\*\*/g, '')}</div>)}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {current?.outline?.lint.filter((l) => l.severity === 'warn').map((w) => (
        <Notice key={w.id} tone="warn">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>{w.message}</span>
            {w.fixable && <Button size="sm" variant="secondary" onClick={async () => setTex((await api.lintFix(tex, w.id)).tex)}>Fix it</Button>}
          </div>
        </Notice>
      ))}
    </div>
  )
}

export type ModelChoice = { key: string; provider: string | null; model: string; ready: boolean }

/** Provider key with a live check, the model list, and the saved-key state. Reports the choice upward. */
export function ModelEditor({ saved, onChange }: { saved: Profile['model']; onChange: (c: ModelChoice) => void }) {
  const [config, setConfig] = useState<Config | null>(null)
  const [key, setKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [pick, setPick] = useState<string | null>(null)
  const [models, setModels] = useState<ModelInfo[]>([])
  const [model, setModel] = useState(saved.model ?? '')
  const [check, setCheck] = useState<{ kind: 'idle' | 'loading' | 'ok' | 'error'; text?: string }>({ kind: 'idle' })
  const provider = pick ?? detectProvider(key) ?? saved.provider

  useEffect(() => {
    void api.config().then(setConfig).catch(() => undefined)
  }, [])
  useEffect(() => {
    const k = key.trim()
    if (!k || !provider) return
    const t = setTimeout(async () => {
      setCheck({ kind: 'loading' })
      try {
        const r = await api.models(k, provider)
        setModels(r.models)
        setModel((m) => (r.models.some((x) => x.id === m) ? m : r.recommended ?? r.models[0]?.id ?? ''))
        setCheck({ kind: 'ok', text: `Key works · ${r.models.length} models` })
      } catch (e) {
        setModels([])
        setCheck({ kind: 'error', text: e instanceof Error ? e.message : 'Could not check the key.' })
      }
    }, 500)
    return () => clearTimeout(t)
  }, [key, provider])

  const ready = check.kind === 'ok' || (!key.trim() && saved.key_saved)
  useEffect(() => onChange({ key: key.trim(), provider, model, ready }), [key, provider, model, ready, onChange])
  const needsProvider = key.trim().length > 10 && !provider

  return (
    <div className="flex flex-col gap-space-md">
      {saved.key_saved && !key.trim() && <Notice tone="good">A key is already saved ({saved.key_hint}) for {saved.provider}. Paste a new one to replace it.</Notice>}
      <Field label="API key">
        <div className="flex gap-2">
          <TextInput type={showKey ? 'text' : 'password'} value={key} onChange={(e) => { setKey(e.target.value); setPick(null) }} placeholder="Paste a key: AIza…, gsk_…, sk-…, sk-ant-…, sk-or-…" autoComplete="off" spellCheck={false} />
          <Button variant="ghost" onClick={() => setShowKey((s) => !s)}>{showKey ? 'Hide' : 'Show'}</Button>
        </div>
      </Field>
      {needsProvider && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-body-sm text-body-sm text-on-surface-variant">Which provider?</span>
          {config?.providers.map((p) => (
            <button key={p.id} type="button" onClick={() => setPick(p.id)} className={`rounded-full border px-3 py-1 font-label-sm text-label-sm ${pick === p.id ? 'border-primary-container bg-primary-fixed/40 text-primary' : 'border-outline-variant text-on-surface-variant hover:bg-surface-container-low'}`}>{p.label}</button>
          ))}
        </div>
      )}
      {check.kind === 'loading' && <div className="flex items-center gap-2 font-body-sm text-body-sm text-on-surface-variant"><Spinner /> Checking the key…</div>}
      {check.kind === 'error' && <Notice tone="bad">{check.text}</Notice>}
      {check.kind === 'ok' && <Notice tone="good">{check.text}</Notice>}
      {models.length > 0 && (
        <Field label="Model">
          <select value={model} onChange={(e) => setModel(e.target.value)} className="w-full rounded-lg border border-outline-variant bg-surface-container-low px-3.5 py-2.5 font-body-md text-body-md">
            {models.map((m) => <option key={m.id} value={m.id}>{m.label && m.label !== m.id ? `${m.label} (${m.id})` : m.id}</option>)}
          </select>
        </Field>
      )}
      {!key.trim() && !saved.key_saved && config && (
        <div className="flex flex-wrap items-center gap-1.5 font-body-sm text-body-sm text-on-surface-variant">
          <span>Need a key? These have free tiers:</span>
          {config.providers.filter((p) => p.free_tier).map((p) => (
            <a key={p.id} href={p.key_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-full bg-primary-fixed/50 px-2.5 py-0.5 font-label-sm text-label-sm text-primary hover:bg-primary-fixed">{p.label} <Icon name="north_east" className="text-[12px]" /></a>
          ))}
        </div>
      )}
    </div>
  )
}
