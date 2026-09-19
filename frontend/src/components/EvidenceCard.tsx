import { useRef, useState } from 'react'
import { api, type Evidence, type EvidenceSource } from '../api'
import { Icon, Spinner } from './Icons'

type Repo = { name: string; description: string; language: string | null; topics: string[]; stars: number; fork: boolean; url: string }

type Props = {
  evidence: Evidence[]
  setEvidence: (e: Evidence[]) => void
  skills: string[]
  setSkills: (s: string[]) => void
  llm: { key: string | null; provider: string | null; model: string | null }
}

type Tab = 'linkedin' | 'portfolio' | 'github' | 'skills' | 'facts'

const TABS: { id: Tab; label: string }[] = [
  { id: 'linkedin', label: 'LinkedIn' },
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'github', label: 'GitHub' },
  { id: 'skills', label: 'Skills' },
  { id: 'facts', label: 'Facts' },
]

const SOURCE_LABEL: Record<EvidenceSource, string> = { linkedin: 'LinkedIn', portfolio: 'Portfolio', github: 'GitHub', fact: 'Facts', skill: 'Skills' }
const GROUP_ORDER: EvidenceSource[] = ['linkedin', 'portfolio', 'github', 'fact']

export function EvidenceCard({ evidence, setEvidence, skills, setSkills, llm }: Props) {
  const [open, setOpen] = useState(evidence.length > 0 || skills.length > 0)
  const [tab, setTab] = useState<Tab>('linkedin')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const replaceSource = (source: EvidenceSource, items: Evidence[]) => {
    setEvidence([...evidence.filter((e) => e.source !== source), ...items])
  }

  const run = async (label: string, work: () => Promise<void>) => {
    setBusy(label)
    setError(null)
    setNote(null)
    try {
      await work()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const readProfile = (kind: 'linkedin' | 'portfolio', payload: { pdf_base64?: string; text?: string; url?: string }) =>
    run(kind === 'linkedin' ? 'Reading your LinkedIn profile…' : 'Reading your portfolio…', async () => {
      const res = await api.profile({ kind, ...payload, key: llm.key, provider: llm.provider, model: llm.model })
      replaceSource(kind, res.evidence)
      setNote(res.note ?? `Found ${res.evidence.length} item${res.evidence.length === 1 ? '' : 's'}. Each one was checked against your ${kind === 'linkedin' ? 'profile' : 'page'}.`)
    })

  const total = evidence.length + skills.length

  return (
    <section className="card">
      <header className="card-head clickable" onClick={() => setOpen((o) => !o)}>
        <span className="step">3</span>
        <div className="grow">
          <h2>
            About you <span className="muted small">optional</span>
            {total > 0 && <span className="pill accent">{total} items</span>}
          </h2>
          <p className="muted">
            Your LinkedIn, portfolio and GitHub, plus skills and facts. TailorTeX uses them to suggest projects and skills worth adding for each job,
            and it only adds what's backed here.
          </p>
        </div>
        <span className={`chevron ${open ? 'open' : ''}`} aria-hidden="true">›</span>
      </header>

      {open && (
        <>
          <div className="tabs small-tabs" role="tablist">
            {TABS.map((t) => {
              const n = t.id === 'skills' ? skills.length : evidence.filter((e) => e.source === (t.id === 'facts' ? 'fact' : t.id)).length
              return (
                <button key={t.id} type="button" role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'active' : ''} onClick={() => { setTab(t.id); setError(null); setNote(null) }}>
                  {t.label}
                  {n > 0 && <span className="tab-count">{n}</span>}
                </button>
              )
            })}
          </div>

          {tab === 'linkedin' && <LinkedInTab busy={!!busy} onRead={(p) => readProfile('linkedin', p)} onError={setError} />}
          {tab === 'portfolio' && <PortfolioTab busy={!!busy} onRead={(p) => readProfile('portfolio', p)} />}
          {tab === 'github' && <GitHubTab busy={busy} run={run} onImport={(items) => { const ids = new Set(items.map((i) => i.id)); setEvidence([...evidence.filter((e) => !ids.has(e.id)), ...items]) }} />}
          {tab === 'skills' && <SkillsTab skills={skills} setSkills={setSkills} />}
          {tab === 'facts' && <FactsTab evidence={evidence} setEvidence={setEvidence} />}

          {busy && <p className="status"><Spinner /> {busy}</p>}
          {error && <p className="status bad"><Icon name="alert" /> {error}</p>}
          {note && !error && <p className="status good"><Icon name="check" /> {note}</p>}

          {(skills.length > 0 || evidence.length > 0) && (
            <div className="evidence-list">
              {skills.length > 0 && (
                <div className="ev-group">
                  <div className="ev-group-head">
                    <strong>Skills you can defend</strong>
                  </div>
                  <div className="chips">
                    {skills.map((s) => (
                      <span key={s} className="chip">
                        {s}
                        <button type="button" aria-label={`Remove ${s}`} onClick={() => setSkills(skills.filter((x) => x !== s))}>×</button>
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {GROUP_ORDER.map((src) => {
                const items = evidence.filter((e) => e.source === src)
                if (!items.length) return null
                return <EvidenceGroup key={src} label={SOURCE_LABEL[src]} items={items} onRemove={(id) => setEvidence(evidence.filter((e) => e.id !== id))} onClear={() => replaceSource(src, [])} />
              })}
            </div>
          )}
        </>
      )}
    </section>
  )
}

function EvidenceGroup({ label, items, onRemove, onClear }: { label: string; items: Evidence[]; onRemove: (id: string) => void; onClear: () => void }) {
  const [all, setAll] = useState(false)
  const shown = all ? items : items.slice(0, 3)
  return (
    <div className="ev-group">
      <div className="ev-group-head">
        <strong>{label}</strong>
        <span className="muted small">{items.length} item{items.length === 1 ? '' : 's'}</span>
        <button type="button" className="link" onClick={onClear}>Remove all</button>
      </div>
      {shown.map((e) => (
        <div key={e.id} className="evidence-item">
          <div className="grow">
            <div>
              <strong>{e.title || e.id}</strong> <span className="muted small">{e.id}</span>
              {e.url && (
                <a className="muted small" href={e.url} target="_blank" rel="noreferrer"> <Icon name="external" /></a>
              )}
            </div>
            {e.text && <div className="muted small clamp">{e.text}</div>}
            {e.skills.length > 0 && <div className="small ev-skills">{e.skills.join(' · ')}</div>}
          </div>
          <button type="button" className="icon-btn" aria-label="Remove" onClick={() => onRemove(e.id)}>
            <Icon name="trash" />
          </button>
        </div>
      ))}
      {items.length > 3 && (
        <button type="button" className="link" onClick={() => setAll((a) => !a)}>
          {all ? 'Show fewer' : `Show all ${items.length}`}
        </button>
      )}
    </div>
  )
}

function LinkedInTab({ busy, onRead, onError }: { busy: boolean; onRead: (p: { pdf_base64?: string; text?: string }) => void; onError: (m: string) => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [paste, setPaste] = useState(false)
  const [text, setText] = useState('')
  const onFile = async (file: File | undefined) => {
    if (!file) return
    if (file.type && file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      onError('Upload the PDF that LinkedIn gives you (More → Save to PDF).')
      return
    }
    if (file.size > 5_000_000) {
      onError('That PDF is larger than 5 MB.')
      return
    }
    const bytes = new Uint8Array(await file.arrayBuffer())
    let bin = ''
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
    onRead({ pdf_base64: btoa(bin) })
  }
  return (
    <div className="stack">
      <ol className="copy-steps">
        <li>Open your profile on LinkedIn.</li>
        <li>Click <strong>More</strong> (or <strong>Resources</strong>) under your name, then <strong>Save to PDF</strong>.</li>
        <li>Upload that PDF here.</li>
      </ol>
      <div className="row wrap gap-s">
        <button type="button" className="btn secondary" disabled={busy} onClick={() => fileRef.current?.click()}>
          <Icon name="upload" /> Upload LinkedIn PDF
        </button>
        <button type="button" className="link" onClick={() => setPaste((p) => !p)}>
          {paste ? 'Hide' : 'or paste your profile text'}
        </button>
        <input ref={fileRef} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = '' }} />
      </div>
      {paste && (
        <>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} placeholder="Paste your About, Experience and Projects sections from LinkedIn" />
          <button type="button" className="btn" disabled={busy || text.trim().length < 80} onClick={() => onRead({ text })}>
            Read it
          </button>
        </>
      )}
      <p className="hint">LinkedIn doesn't let apps read a profile from its link, so the PDF LinkedIn gives you is the reliable way. It's read once and not stored on the server.</p>
    </div>
  )
}

function PortfolioTab({ busy, onRead }: { busy: boolean; onRead: (p: { url?: string; text?: string }) => void }) {
  const [url, setUrl] = useState('')
  const [paste, setPaste] = useState(false)
  const [text, setText] = useState('')
  return (
    <div className="stack">
      <div className="input-group">
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="yourname.dev" onKeyDown={(e) => e.key === 'Enter' && url.trim() && onRead({ url })} />
        <button type="button" className="btn secondary" disabled={busy || !url.trim()} onClick={() => onRead({ url })}>
          Read my portfolio
        </button>
      </div>
      <button type="button" className="link" style={{ alignSelf: 'flex-start' }} onClick={() => setPaste((p) => !p)}>
        {paste ? 'Hide' : 'or paste its text'}
      </button>
      {paste && (
        <>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} placeholder="Paste your portfolio's About and Projects text" />
          <button type="button" className="btn" disabled={busy || text.trim().length < 80} onClick={() => onRead({ text })}>
            Read it
          </button>
        </>
      )}
      <p className="hint">Reads the page's text, once. Portfolios built entirely with JavaScript may need the paste option.</p>
    </div>
  )
}

function GitHubTab({ busy, run, onImport }: { busy: string | null; run: (label: string, work: () => Promise<void>) => Promise<void>; onImport: (items: Evidence[]) => void }) {
  const [username, setUsername] = useState('')
  const [repos, setRepos] = useState<Repo[]>([])
  const [picked, setPicked] = useState<Set<string>>(new Set())

  const find = () =>
    run('Looking up your repositories…', async () => {
      const res = await api.githubRepos(username.trim())
      setRepos(res.repos)
      setPicked(new Set(res.repos.filter((r) => !r.fork).slice(0, 4).map((r) => r.name)))
      if (!res.repos.length) throw new Error('No public repositories found.')
    })

  const add = () =>
    run('Reading the repositories you picked…', async () => {
      const res = await api.githubImport(username.trim(), [...picked])
      onImport(res.evidence)
      setRepos([])
    })

  return (
    <div className="stack">
      <div className="input-group">
        <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="GitHub username" onKeyDown={(e) => e.key === 'Enter' && username.trim() && find()} />
        <button type="button" className="btn secondary" disabled={!username.trim() || !!busy} onClick={find}>
          <Icon name="github" /> Find repos
        </button>
      </div>
      {repos.length > 0 && (
        <>
          <p className="muted small">Tick the projects that show your best work. Their descriptions, languages and READMEs become context for tailoring.</p>
          <div className="repo-list">
            {repos.map((r) => (
              <label key={r.name} className="repo">
                <input
                  type="checkbox"
                  checked={picked.has(r.name)}
                  disabled={!picked.has(r.name) && picked.size >= 8}
                  onChange={(e) => {
                    const next = new Set(picked)
                    if (e.target.checked) next.add(r.name)
                    else next.delete(r.name)
                    setPicked(next)
                  }}
                />
                <span>
                  <strong>{r.name}</strong> {r.fork && <span className="pill muted-pill">fork</span>}
                  {r.language && <span className="muted small"> · {r.language}</span>}
                  {r.stars > 0 && <span className="muted small"> · ★ {r.stars}</span>}
                  {r.description && <span className="repo-desc">{r.description}</span>}
                </span>
              </label>
            ))}
          </div>
          <button type="button" className="btn" disabled={!picked.size || !!busy} onClick={add}>
            Use {picked.size} project{picked.size === 1 ? '' : 's'} as context
          </button>
        </>
      )}
      <p className="hint">Public repos only, through GitHub's public API. No login, and nothing on GitHub changes.</p>
    </div>
  )
}

function SkillsTab({ skills, setSkills }: { skills: string[]; setSkills: (s: string[]) => void }) {
  const [input, setInput] = useState('')
  const add = () => {
    const next = [...skills]
    for (const s of input.split(/[,\n]/).map((x) => x.trim()).filter(Boolean)) {
      if (!next.some((x) => x.toLowerCase() === s.toLowerCase())) next.push(s)
    }
    setSkills(next)
    setInput('')
  }
  return (
    <div className="stack">
      <div className="input-group">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. AWS, Kafka (press Enter)"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && input.trim()) {
              e.preventDefault()
              add()
            }
          }}
        />
        <button type="button" className="btn secondary" disabled={!input.trim()} onClick={add}>
          Add
        </button>
      </div>
      <p className="hint">Skills you could defend in an interview. They can go into your skills lines and summary, never into a specific job's bullets.</p>
    </div>
  )
}

function FactsTab({ evidence, setEvidence }: { evidence: Evidence[]; setEvidence: (e: Evidence[]) => void }) {
  const [fact, setFact] = useState('')
  const [title, setTitle] = useState('')
  const add = () => {
    const n = Math.max(0, ...evidence.filter((e) => /^f\d+$/.test(e.id)).map((e) => Number(e.id.slice(1)))) + 1
    setEvidence([...evidence, { id: `f${n}`, source: 'fact', title: title.trim(), text: fact.trim(), skills: [] }])
    setFact('')
    setTitle('')
  }
  return (
    <div className="stack">
      <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Where (optional), e.g. Finch Payments" />
      <textarea value={fact} onChange={(e) => setFact(e.target.value)} rows={3} placeholder="e.g. At Finch Payments I built Kafka consumers that process settlement events." />
      <button type="button" className="btn secondary" disabled={!fact.trim()} onClick={add}>
        <Icon name="plus" /> Add fact
      </button>
      <p className="hint">Facts can back new bullets, including their numbers. Say where it happened so it lands under the right job.</p>
    </div>
  )
}
