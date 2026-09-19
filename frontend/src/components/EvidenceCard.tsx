import { useRef, useState } from 'react'
import { api, type Evidence, type EvidenceSource, type LinkResult } from '../api'
import { noteLines, store } from '../util'
import { Icon, Spinner } from './Icons'

type Props = {
  evidence: Evidence[]
  setEvidence: (e: Evidence[]) => void
  skills: string[]
  setSkills: (s: string[]) => void
  notes: string
  setNotes: (s: string) => void
  llm: { key: string | null; provider: string | null; model: string | null }
}

const SOURCE_LABEL: Record<EvidenceSource, string> = { linkedin: 'LinkedIn', portfolio: 'Portfolio', github: 'GitHub', fact: 'Facts', skill: 'Skills' }
const GROUP_ORDER: EvidenceSource[] = ['github', 'portfolio', 'linkedin', 'fact']

export function EvidenceCard({ evidence, setEvidence, skills, setSkills, notes, setNotes, llm }: Props) {
  const [open, setOpen] = useState(true)
  const [github, setGithub] = useState(() => store.get('githubLink', ''))
  const [portfolio, setPortfolio] = useState(() => store.get('portfolioLink', ''))
  const [results, setResults] = useState<LinkResult[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [draft, setDraftState] = useState(() => store.get('notesDraft', ''))
  const setDraft = (v: string) => {
    setDraftState(v)
    store.set('notesDraft', v)
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

  const readLinks = () =>
    run('Reading your GitHub and portfolio…', async () => {
      store.set('githubLink', github)
      store.set('portfolioLink', portfolio)
      const gh = github.trim() && !/github\.com/i.test(github) ? `github.com/${github.trim().replace(/^@/, '')}` : github.trim()
      const res = await api.links({ links: [gh, portfolio.trim()].filter(Boolean), ...llm })
      setResults(res.results)
      // A fresh read replaces what was read before from the same place.
      let next = evidence.filter((e) => !(e.source === 'github' && gh) && !(e.source === 'portfolio' && portfolio.trim()))
      for (const r of res.results) next = [...next, ...renumber(r.evidence, next)]
      setEvidence(next)
      if (res.notes.length) setNote(res.notes.join(' '))
    })

  const readLinkedIn = (file: File | undefined) => {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.pdf')) return setError('Upload the PDF from LinkedIn: on your profile, More → Save to PDF.')
    if (file.size > 5_000_000) return setError('That PDF is larger than 5 MB.')
    run('Reading your LinkedIn…', async () => {
      const res = await api.profile({ kind: 'linkedin', pdf_base64: await toBase64(file), ...llm })
      const kept = evidence.filter((e) => e.source !== 'linkedin')
      setEvidence([...kept, ...renumber(res.evidence, kept)])
      setNote(res.note ?? `Found ${res.evidence.length} items on your LinkedIn.`)
    })
  }

  const lines = noteLines(notes)
  const draftLines = noteLines(draft)
  const saveNotes = () => {
    if (!draftLines.length) return
    const fresh = draftLines.filter((l) => !lines.includes(l))
    setNotes([...lines, ...fresh].join('\n'))
    setDraft('')
    setError(null)
    setNote(fresh.length ? `Saved ${fresh.length} note${fresh.length === 1 ? '' : 's'}. They'll be used in your next run.` : 'Those are already saved.')
  }
  const removeNote = (i: number) => setNotes(lines.filter((_, j) => j !== i).join('\n'))
  const linkedinCount = evidence.filter((e) => e.source === 'linkedin').length
  const total = evidence.length + skills.length + lines.length

  return (
    <section className="card">
      <header className="card-head clickable" onClick={() => setOpen((o) => !o)}>
        <span className="step">3</span>
        <div className="grow">
          <h2>
            About you <span className="muted small">optional</span>
            {total > 0 && <span className="pill accent">{total} items</span>}
          </h2>
          <p className="muted">TailorTeX suggests what's worth adding for each job from what's here, and it only adds what's backed here.</p>
        </div>
        <span className={`chevron ${open ? 'open' : ''}`} aria-hidden="true">›</span>
      </header>

      {open && (
        <>
          <div className="about-grid">
            <label className="field">
              <span className="label-row">
                <span><Icon name="github" /> GitHub</span>
                <ResultTag result={results.find((r) => r.kind.startsWith('github'))} />
              </span>
              <input value={github} onChange={(e) => setGithub(e.target.value)} placeholder="github.com/yourname" spellCheck={false} />
            </label>
            <label className="field">
              <span className="label-row">
                <span><Icon name="external" /> Portfolio</span>
                <ResultTag result={results.find((r) => r.kind === 'portfolio')} />
              </span>
              <input value={portfolio} onChange={(e) => setPortfolio(e.target.value)} placeholder="yourname.dev" spellCheck={false} />
            </label>
          </div>
          <button type="button" className="btn secondary" style={{ alignSelf: 'flex-start' }} disabled={!!busy || (!github.trim() && !portfolio.trim())} onClick={readLinks}>
            Read my GitHub and portfolio
          </button>
          {results.filter((r) => r.error).map((r) => (
            <p key={r.link} className="status bad"><Icon name="alert" /> {r.link}: {r.error}</p>
          ))}

          <div className="field">
            <span className="label-row">
              <span>LinkedIn</span>
              {linkedinCount > 0 && <span className="pill accent">{linkedinCount} items</span>}
            </span>
            <div className="linkedin-row">
              <button type="button" className="btn secondary" disabled={!!busy} onClick={() => fileRef.current?.click()}>
                <Icon name="upload" /> Upload LinkedIn PDF
              </button>
              <span className="muted small">
                On your LinkedIn profile, click <strong>More</strong> → <strong>Save to PDF</strong>.
              </span>
            </div>
            <input ref={fileRef} type="file" accept=".pdf,application/pdf" hidden onChange={(e) => { readLinkedIn(e.target.files?.[0]); e.target.value = '' }} />
          </div>

          <div className="field">
            <span className="label-row">
              <span>Anything else about you</span>
              {lines.length > 0 && <span className="pill accent">{lines.length} saved</span>}
            </span>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault()
                  saveNotes()
                }
              }}
              rows={4}
              placeholder={
                'One thing per line, in your own words. For example:\n' +
                'At Finch Payments I also built Kafka consumers for settlement events\n' +
                'Won 2nd place at DevHacks 2025 with a Flutter app\n' +
                'Led the robotics club (12 members) in college'
              }
            />
            <div className="row wrap gap-s">
              <button type="button" className={draftLines.length ? 'btn' : 'btn secondary'} disabled={!draftLines.length} onClick={saveNotes}>
                <Icon name="check" /> {draftLines.length ? `Save ${draftLines.length} line${draftLines.length === 1 ? '' : 's'}` : 'Save'}
              </button>
              <span className="hint">Ctrl/⌘ + Enter also saves. Say where something happened so it lands under the right job; numbers are used exactly as you write them.</span>
            </div>
          </div>

          {busy && <p className="status"><Spinner /> {busy}</p>}
          {error && <p className="status bad"><Icon name="alert" /> {error}</p>}
          {note && !error && <p className="status good"><Icon name="check" /> {note}</p>}

          {(skills.length > 0 || evidence.length > 0 || lines.length > 0) && (
            <div className="evidence-list">
              {lines.length > 0 && (
                <div className="ev-group">
                  <div className="ev-group-head">
                    <strong>Your notes</strong>
                    <span className="muted small">{lines.length} saved</span>
                    <button type="button" className="link" onClick={() => setNotes('')}>Remove all</button>
                  </div>
                  {lines.map((line, i) => (
                    <div key={`${i}-${line}`} className="evidence-item">
                      <div className="grow small">{line} <span className="muted">n{i + 1}</span></div>
                      <button type="button" className="icon-btn" aria-label="Remove note" onClick={() => removeNote(i)}>
                        <Icon name="trash" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {skills.length > 0 && (
                <div className="ev-group">
                  <div className="ev-group-head">
                    <strong>Skills you confirmed</strong>
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
                return (
                  <EvidenceGroup
                    key={src}
                    label={SOURCE_LABEL[src]}
                    items={items}
                    onRemove={(id) => setEvidence(evidence.filter((e) => e.id !== id))}
                    onClear={() => setEvidence(evidence.filter((e) => e.source !== src))}
                  />
                )
              })}
            </div>
          )}
        </>
      )}
    </section>
  )
}

function ResultTag({ result }: { result: LinkResult | undefined }) {
  if (!result || result.error) return null
  const n = result.evidence.length
  return <span className="pill accent">{n} item{n === 1 ? '' : 's'}</span>
}

/** Give new items IDs that don't clash with ones already there. */
function renumber(items: Evidence[], existing: Evidence[]): Evidence[] {
  const taken = new Set(existing.map((e) => e.id))
  return items.map((item) => {
    if (!taken.has(item.id)) {
      taken.add(item.id)
      return item
    }
    const prefix = item.id.replace(/\d+$/, '')
    let n = 1
    while (taken.has(`${prefix}${n}`)) n++
    taken.add(`${prefix}${n}`)
    return { ...item, id: `${prefix}${n}` }
  })
}

async function toBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let bin = ''
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(bin)
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
