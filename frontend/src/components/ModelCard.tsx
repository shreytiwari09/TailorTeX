import { useEffect, useRef, useState } from 'react'
import { api, detectProvider, type Config, type ModelInfo } from '../api'
import { Icon, Spinner } from './Icons'

type Props = {
  config: Config | null
  apiKey: string
  setApiKey: (k: string) => void
  provider: string | null
  setProvider: (p: string | null) => void
  model: string
  setModel: (m: string) => void
  remember: boolean
  setRemember: (r: boolean) => void
}

type Status = { kind: 'idle' | 'loading' | 'ok' | 'error'; message?: string }

export function ModelCard({ config, apiKey, setApiKey, provider, setProvider, model, setModel, remember, setRemember }: Props) {
  const [models, setModels] = useState<ModelInfo[]>([])
  const [status, setStatus] = useState<Status>({ kind: 'idle' })
  const [showKey, setShowKey] = useState(false)
  const [override, setOverride] = useState(false)
  const lastChecked = useRef('')

  const usingServerKey = !apiKey.trim() && !!config?.server_key
  const detected = detectProvider(apiKey)
  const effectiveProvider = usingServerKey ? config?.server_provider ?? null : provider
  const providerInfo = config?.providers.find((p) => p.id === effectiveProvider)

  // Follow the key's detected provider unless the user picked one by hand.
  useEffect(() => {
    if (!override) setProvider(detected)
  }, [detected, override, setProvider])

  // Check the key and load the live model list once the key and provider are known.
  useEffect(() => {
    const k = apiKey.trim()
    if (!config) return
    if (!k && !config.server_key) {
      setModels([])
      setStatus({ kind: 'idle' })
      return
    }
    if (k && !provider) {
      setModels([])
      setStatus(k.length > 10 ? { kind: 'error', message: "Couldn't tell which provider this key is for. Pick it below." } : { kind: 'idle' })
      return
    }
    const sig = `${k}|${provider}`
    if (sig === lastChecked.current) return
    const t = setTimeout(async () => {
      lastChecked.current = sig
      setStatus({ kind: 'loading' })
      try {
        const res = await api.models(k, k ? provider : null)
        setModels(res.models)
        const keep = res.models.some((m) => m.id === model)
        if (!keep && res.recommended) setModel(res.recommended)
        setStatus({ kind: 'ok', message: `${k ? 'Key works' : "Using the server's key"} · ${res.models.length} models` })
      } catch (e) {
        lastChecked.current = ''
        setModels([])
        setStatus({ kind: 'error', message: (e as Error).message })
      }
    }, 500)
    return () => clearTimeout(t)
    // model is read, not tracked: changing the model shouldn't re-check the key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiKey, provider, config])

  const selected = models.find((m) => m.id === model)

  return (
    <section className="card">
      <header className="card-head">
        <span className="step">1</span>
        <div>
          <h2>Model</h2>
          <p className="muted">Bring your own key from any of 7 providers. It's used only for your requests and never stored on the server.</p>
        </div>
      </header>

      {config?.server_key && !apiKey.trim() && (
        <div className="note ok-note">
          <Icon name="check" /> This server has a built-in key ({config.server_provider}). You can use it, or paste your own.
        </div>
      )}

      <label className="field">
        <span className="label-row">
          <span>API key</span>
          {providerInfo && !usingServerKey && <span className="pill accent">{providerInfo.label}</span>}
        </span>
        <div className="input-group">
          <input
            type={showKey ? 'text' : 'password'}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Paste a key: AIza…, gsk_…, sk-…, sk-ant-…, sk-or-…"
            autoComplete="off"
            spellCheck={false}
          />
          <button type="button" className="btn ghost small" onClick={() => setShowKey((s) => !s)}>
            {showKey ? 'Hide' : 'Show'}
          </button>
        </div>
      </label>

      <div className="row wrap gap-s">
        <label className="check">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Remember on this device
        </label>
        <span className="hint">{remember ? 'Saved in this browser only, never on our server.' : 'Kept until you close this tab.'}</span>
        {apiKey.trim() && (
          <button type="button" className="link" onClick={() => setOverride((o) => !o)}>
            {override ? 'Detect provider from key' : 'Wrong provider?'}
          </button>
        )}
      </div>

      {apiKey.trim() && (override || !detected) && (
        <label className="field">
          <span>Provider</span>
          <select value={provider ?? ''} onChange={(e) => { setOverride(true); setProvider(e.target.value || null) }}>
            <option value="">Choose…</option>
            {config?.providers.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
        </label>
      )}

      {status.kind === 'loading' && <p className="status"><Spinner /> Checking the key…</p>}
      {status.kind === 'error' && <p className="status bad"><Icon name="alert" /> {status.message}</p>}
      {status.kind === 'ok' && <p className="status good"><Icon name="check" /> {status.message}</p>}

      {models.length > 0 && (
        <label className="field">
          <span>Model</span>
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label && m.label !== m.id ? `${m.label} (${m.id})` : m.id}
              </option>
            ))}
          </select>
          {selected?.price_in != null && selected.price_out != null && (
            <span className="hint">${selected.price_in.toFixed(2)} in / ${selected.price_out.toFixed(2)} out per million tokens</span>
          )}
        </label>
      )}

      {!apiKey.trim() && !config?.server_key && (
        <div className="key-help">
          <span className="muted">No key yet? These have free tiers:</span>
          <div className="row wrap gap-s">
            {config?.providers.filter((p) => p.free_tier).map((p) => (
              <a key={p.id} className="pill link-pill" href={p.key_url} target="_blank" rel="noreferrer">
                {p.label} <Icon name="external" />
              </a>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
