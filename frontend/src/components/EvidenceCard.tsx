import { useState } from 'react'
import { api, type Evidence } from '../api'
import { Icon, Spinner } from './Icons'

type Repo = { name: string; description: string; language: string | null; topics: string[]; stars: number; fork: boolean; url: string }

type Props = {
  evidence: Evidence[]
  setEvidence: (e: Evidence[]) => void
  skills: string[]
  setSkills: (s: string[]) => void
}

const SOURCE_LABEL: Record<string, string> = { github: 'GitHub', fact: 'Fact', skill: 'Skill', portfolio: 'Portfolio', linkedin: 'LinkedIn' }

export function EvidenceCard({ evidence, setEvidence, skills, setSkills }: Props) {
  const [open, setOpen] = useState(evidence.length > 0 || skills.length > 0)
  const [tab, setTab] = useState<'github' | 'skills' | 'facts'>('github')
  const [username, setUsername] = useState('')
  const [repos, setRepos] = useState<Repo[]>([])
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [skillInput, setSkillInput] = useState('')
  const [fact, setFact] = useState('')
  const [factTitle, setFactTitle] = useState('')

  const findRepos = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await api.githubRepos(username.trim())
      setRepos(res.repos)
      setPicked(new Set(res.repos.filter((r) => !r.fork).slice(0, 4).map((r) => r.name)))
      if (!res.repos.length) setError('No public repositories found.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const importRepos = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await api.githubImport(username.trim(), [...picked])
      const ids = new Set(res.evidence.map((e) => e.id))
      setEvidence([...evidence.filter((e) => !ids.has(e.id)), ...res.evidence])
      setRepos([])
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const addSkills = (raw: string) => {
    const add = raw.split(/[,\n]/).map((s) => s.trim()).filter(Boolean)
    const next = [...skills]
    for (const s of add) if (!next.some((x) => x.toLowerCase() === s.toLowerCase())) next.push(s)
    setSkills(next)
    setSkillInput('')
  }

  const addFact = () => {
    if (!fact.trim()) return
    const n = Math.max(0, ...evidence.filter((e) => /^f\d+$/.test(e.id)).map((e) => Number(e.id.slice(1)))) + 1
    setEvidence([...evidence, { id: `f${n}`, source: 'fact', title: factTitle.trim(), text: fact.trim(), skills: [] }])
    setFact('')
    setFactTitle('')
  }

  const count = evidence.length + (skills.length ? 1 : 0)

  return (
    <section className="card">
      <header className="card-head clickable" onClick={() => setOpen((o) => !o)}>
        <span className="step">3</span>
        <div className="grow">
          <h2>
            Evidence <span className="muted small">optional</span>
            {count > 0 && <span className="pill accent">{evidence.length + skills.length} items</span>}
          </h2>
          <p className="muted">
            True things about you that aren't on the resume yet. TailorTeX can only add a job's keyword if you have evidence for it.
          </p>
        </div>
        <span className={`chevron ${open ? 'open' : ''}`} aria-hidden="true">›</span>
      </header>

      {open && (
        <>
          <div className="tabs small-tabs" role="tablist">
            {(['github', 'skills', 'facts'] as const).map((t) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
                {t === 'github' ? 'GitHub repos' : t === 'skills' ? 'Skills I can defend' : 'Facts'}
              </button>
            ))}
          </div>

          {tab === 'github' && (
            <div className="stack">
              <div className="input-group">
                <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="GitHub username" onKeyDown={(e) => e.key === 'Enter' && username.trim() && findRepos()} />
                <button type="button" className="btn secondary" disabled={!username.trim() || busy} onClick={findRepos}>
                  <Icon name="github" /> Find repos
                </button>
              </div>
              {repos.length > 0 && (
                <>
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
                  <button type="button" className="btn" disabled={!picked.size || busy} onClick={importRepos}>
                    Import {picked.size} repo{picked.size === 1 ? '' : 's'}
                  </button>
                </>
              )}
              <p className="hint">Reads public repo descriptions, languages and READMEs through GitHub's public API. Up to 8 repos.</p>
            </div>
          )}

          {tab === 'skills' && (
            <div className="stack">
              <div className="input-group">
                <input
                  value={skillInput}
                  onChange={(e) => setSkillInput(e.target.value)}
                  placeholder="e.g. AWS, Kafka (press Enter)"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && skillInput.trim()) {
                      e.preventDefault()
                      addSkills(skillInput)
                    }
                  }}
                />
                <button type="button" className="btn secondary" disabled={!skillInput.trim()} onClick={() => addSkills(skillInput)}>
                  Add
                </button>
              </div>
              <p className="hint">Skills you could defend in an interview. They can go into your skills lines and summary, never into a specific job's bullets.</p>
            </div>
          )}

          {tab === 'facts' && (
            <div className="stack">
              <input value={factTitle} onChange={(e) => setFactTitle(e.target.value)} placeholder="Where (optional), e.g. Finch Payments" />
              <textarea value={fact} onChange={(e) => setFact(e.target.value)} rows={3} placeholder="e.g. At Finch Payments I built Kafka consumers that process settlement events." />
              <button type="button" className="btn secondary" disabled={!fact.trim()} onClick={addFact}>
                <Icon name="plus" /> Add fact
              </button>
              <p className="hint">Facts can back new bullets, including their numbers. Say where it happened so it lands under the right job.</p>
            </div>
          )}

          {busy && <p className="status"><Spinner /> Talking to GitHub…</p>}
          {error && <p className="status bad"><Icon name="alert" /> {error}</p>}

          {(skills.length > 0 || evidence.length > 0) && (
            <div className="evidence-list">
              {skills.length > 0 && (
                <div className="chips">
                  {skills.map((s) => (
                    <span key={s} className="chip">
                      {s}
                      <button type="button" aria-label={`Remove ${s}`} onClick={() => setSkills(skills.filter((x) => x !== s))}>×</button>
                    </span>
                  ))}
                </div>
              )}
              {evidence.map((e) => (
                <div key={e.id} className="evidence-item">
                  <span className={`pill src-${e.source}`}>{SOURCE_LABEL[e.source] ?? e.source}</span>
                  <div className="grow">
                    <div>
                      <strong>{e.title || e.id}</strong> <span className="muted small">{e.id}</span>
                    </div>
                    {e.text && <div className="muted small clamp">{e.text}</div>}
                    {e.skills.length > 0 && <div className="muted small">{e.skills.join(' · ')}</div>}
                  </div>
                  <button type="button" className="icon-btn" aria-label="Remove" onClick={() => setEvidence(evidence.filter((x) => x.id !== e.id))}>
                    <Icon name="trash" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
