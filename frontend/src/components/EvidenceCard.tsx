import { useRef, useState } from 'react'
import { api, type Evidence, type EvidenceSource, type LinkResult, type ProfileRequest } from '../api'
import { store } from '../util'
import { Icon, Spinner } from './Icons'

type Repo = { name: string; description: string; language: string | null; topics: string[]; stars: number; fork: boolean; url: string }

type Props = {
  evidence: Evidence[]
  setEvidence: (e: Evidence[]) => void
  skills: string[]
  setSkills: (s: string[]) => void
  llm: { key: string | null; provider: string | null; model: string | null }
}

type MoreTab = 'skills' | 'facts' | 'paste' | 'repos'

const SOURCE_LABEL: Record<EvidenceSource, string> = { linkedin: 'LinkedIn', portfolio: 'Portfolio', github: 'GitHub', fact: 'Facts', skill: 'Skills' }
const GROUP_ORDER: EvidenceSource[] = ['linkedin', 'portfolio', 'github', 'fact']
const KIND_LABEL: Record<LinkResult['kind'], string> = {
  github_user: 'GitHub',
  github_repo: 'GitHub',
  linkedin: 'LinkedIn',
  portfolio: 'Website',
  invalid: 'Link',
}

export function EvidenceCard({ evidence, setEvidence, skills, setSkills, llm }: Props) {
  const [open, setOpen] = useState(true)
  const [links, setLinks] = useState(() => store.get('links', ''))
  const [results, setResults] = useState<LinkResult[]>([])
  const [linkedinUrl, setLinkedinUrl] = useState<string | null>(() => store.get<string | null>('linkedinUrl', null))
  const [more, setMore] = useState<MoreTab | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  /** Add imported items: drop older copies of the same items, and keep IDs unique. */
  const merge = (current: Evidence[], incoming: Evidence[], replacesPrefixes: string[] = []) => {
    const incomingIds = new Set(incoming.map((e) => e.id))
    const incomingUrls = new Set(incoming.filter((e) => e.source === 'portfolio' && e.url).map((e) => e.url))
    const stale = (e: Evidence) =>
      (e.source === 'github' && incomingIds.has(e.id)) ||
      (e.source === 'portfolio' && !!e.url && incomingUrls.has(e.url)) ||
      replacesPrefixes.some((pre) => new RegExp(`^${pre}\\d+$`).test(e.id))
    const kept = current.filter((e) => !stale(e))
    return [...kept, ...renumber(incoming, kept)]
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

  const addLinks = () =>
    run('Reading your links…', async () => {
      store.set('links', links)
      const res = await api.links({ links: [links], ...llm })
      setResults(res.results)
      let next = evidence
      for (const r of res.results) next = merge(next, r.evidence)
      setEvidence(next)
      const li = res.results.find((r) => r.kind === 'linkedin')
      if (li?.url) {
        setLinkedinUrl(li.url)
        store.set('linkedinUrl', li.url)
      }
      if (res.notes.length) setNote(res.notes.join(' '))
    })

  const readProfile = (payload: ProfileRequest) =>
    run(payload.kind === 'portfolio' ? 'Reading the text…' : 'Reading your LinkedIn…', async () => {
      const res = await api.profile({ ...payload, ...llm })
      setEvidence(merge(evidence, res.evidence, res.replaces))
      const newSkills = res.skills.filter((sk) => !skills.some((x) => x.toLowerCase() === sk.toLowerCase()))
      if (newSkills.length) setSkills([...skills, ...newSkills])
      setNote((res.note ?? `Found ${res.evidence.length} items.`) + (newSkills.length ? ` Added ${newSkills.length} skills from your LinkedIn.` : ''))
    })

  const total = evidence.length + skills.length
  const hasLinkedIn = evidence.some((e) => e.source === 'linkedin')

  return (
    <section className="card">
      <header className="card-head clickable" onClick={() => setOpen((o) => !o)}>
        <span className="step">3</span>
        <div className="grow">
          <h2>
            About you <span className="muted small">optional</span>
            {total > 0 && <span className="pill accent">{total} items</span>}
          </h2>
          <p className="muted">Your GitHub, portfolio and LinkedIn. TailorTeX suggests what's worth adding for each job, and only adds what's backed here.</p>
        </div>
        <span className={`chevron ${open ? 'open' : ''}`} aria-hidden="true">›</span>
      </header>

      {open && (
        <>
          <div className="stack">
            <textarea
              className="links-box"
              rows={2}
              value={links}
              onChange={(e) => setLinks(e.target.value)}
              placeholder={'Paste your links: github.com/yourname  yourname.dev  linkedin.com/in/yourname'}
              spellCheck={false}
            />
            <button type="button" className="btn" disabled={!!busy || !links.trim()} onClick={addLinks} style={{ alignSelf: 'flex-start' }}>
              <Icon name="plus" /> Add links
            </button>
            {results.length > 0 && (
              <ul className="link-results">
                {results.map((r) => (
                  <li key={r.link} className={r.error ? 'bad' : r.kind === 'linkedin' ? 'info' : 'good'}>
                    <Icon name={r.error ? 'alert' : r.kind === 'linkedin' ? 'info' : 'check'} />
                    <span>
                      <strong>{KIND_LABEL[r.kind]}</strong> <span className="muted">{r.link}</span>: {r.error ?? r.note}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <LinkedInDrop
            busy={!!busy}
            profileUrl={linkedinUrl}
            done={hasLinkedIn}
            attention={results.some((r) => r.kind === 'linkedin') && !hasLinkedIn}
            onRead={readProfile}
            onError={setError}
          />

          {busy && <p className="status"><Spinner /> {busy}</p>}
          {error && <p className="status bad"><Icon name="alert" /> {error}</p>}
          {note && !error && <p className="status good"><Icon name="check" /> {note}</p>}

          <div className="more-ways">
            <span className="muted small">More ways to add context:</span>
            {(
              [
                ['skills', 'Skills you can defend'],
                ['facts', 'Facts'],
                ['paste', 'Paste text'],
                ['repos', 'Choose GitHub repos'],
              ] as [MoreTab, string][]
            ).map(([id, label]) => (
              <button key={id} type="button" className={`chip-btn ${more === id ? 'active' : ''}`} onClick={() => setMore(more === id ? null : id)}>
                {label}
                {id === 'skills' && skills.length > 0 && <span className="tab-count">{skills.length}</span>}
              </button>
            ))}
          </div>
          {more === 'skills' && <SkillsTab skills={skills} setSkills={setSkills} />}
          {more === 'facts' && <FactsTab evidence={evidence} setEvidence={setEvidence} />}
          {more === 'paste' && <PasteTab busy={!!busy} onRead={readProfile} />}
          {more === 'repos' && <GitHubTab busy={busy} run={run} onImport={(items) => setEvidence(merge(evidence, items))} />}

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

/** Give new items IDs that don't clash with ones already there (pasted posts add up: pp1, pp2, ...). */
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

function LinkedInDrop(props: {
  busy: boolean
  profileUrl: string | null
  done: boolean
  attention: boolean
  onRead: (p: ProfileRequest) => void
  onError: (m: string) => void
}) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [how, setHow] = useState(false)

  const onFile = async (file: File | undefined) => {
    if (!file) return
    const name = file.name.toLowerCase()
    if (name.endsWith('.pdf')) {
      if (file.size > 5_000_000) return props.onError('That PDF is larger than 5 MB.')
      props.onRead({ kind: 'linkedin', pdf_base64: await toBase64(file) })
    } else if (name.endsWith('.zip')) {
      if (file.size > 20_000_000) return props.onError('That ZIP is larger than 20 MB. Ask LinkedIn for just posts, profile, positions, projects and skills.')
      props.onRead({ kind: 'linkedin', zip_base64: await toBase64(file) })
    } else {
      props.onError('Drop the PDF from LinkedIn (More → Save to PDF), or the ZIP of your LinkedIn data.')
    }
  }

  return (
    <div
      className={`linkedin-drop ${dragging ? 'dragging' : ''} ${props.attention ? 'attention' : ''}`}
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        onFile(e.dataTransfer.files[0])
      }}
    >
      <div className="row gap-s wrap">
        <strong>LinkedIn</strong>
        {props.done ? <span className="pill accent">added</span> : <span className="muted small">one file, about 10 seconds</span>}
      </div>
      <p className="small">
        On your profile, click <strong>More</strong> → <strong>Save to PDF</strong>, then drop the file here.
      </p>
      <div className="row wrap gap-s">
        <button type="button" className="btn secondary small" disabled={props.busy} onClick={() => fileRef.current?.click()}>
          <Icon name="upload" /> Choose file
        </button>
        {props.profileUrl && (
          <a className="btn ghost small" href={props.profileUrl} target="_blank" rel="noreferrer">
            Open my profile <Icon name="external" />
          </a>
        )}
        <button type="button" className="link" onClick={() => setHow((h) => !h)}>
          {how ? 'Hide' : 'Want your posts too?'}
        </button>
      </div>
      {how && (
        <ol className="copy-steps">
          <li>On LinkedIn: <strong>Settings → Data privacy → Get a copy of your data</strong>.</li>
          <li>Pick <strong>"Want something in particular?"</strong>, tick <strong>Posts, Profile, Positions, Projects, Skills</strong>, and request it.</li>
          <li>LinkedIn emails a ZIP within minutes. Drop it here instead of the PDF. Only those files are read; messages and connections are ignored.</li>
        </ol>
      )}
      <input ref={fileRef} type="file" accept=".pdf,.zip,application/pdf,application/zip" hidden onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = '' }} />
    </div>
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

function PasteTab({ busy, onRead }: { busy: boolean; onRead: (p: ProfileRequest) => void }) {
  const [kind, setKind] = useState<ProfileRequest['kind']>('linkedin_posts')
  const [text, setText] = useState('')
  const placeholder = {
    linkedin_posts: 'Paste one or more of your LinkedIn posts about your work',
    linkedin: 'Paste your LinkedIn About, Experience and Projects sections',
    portfolio: "Paste your portfolio's About and Projects text",
  }[kind]
  return (
    <div className="stack">
      <select value={kind} onChange={(e) => setKind(e.target.value as ProfileRequest['kind'])}>
        <option value="linkedin_posts">LinkedIn posts</option>
        <option value="linkedin">LinkedIn profile text</option>
        <option value="portfolio">Portfolio or other text about your work</option>
      </select>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={5} placeholder={placeholder} />
      <button type="button" className="btn secondary" style={{ alignSelf: 'flex-start' }} disabled={busy || text.trim().length < 60} onClick={() => onRead({ kind, text })}>
        Read it
      </button>
    </div>
  )
}

function GitHubTab({ busy, run, onImport }: { busy: string | null; run: (label: string, work: () => Promise<void>) => Promise<void>; onImport: (items: Evidence[]) => void }) {
  const [username, setUsername] = useState('')
  const [repos, setRepos] = useState<Repo[]>([])
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const user = () => username.trim().replace(/^.*github\.com\//i, '').replace(/\/.*$/, '')

  const find = () =>
    run('Looking up your repositories…', async () => {
      const res = await api.githubRepos(user())
      setRepos(res.repos)
      setPicked(new Set(res.repos.filter((r) => !r.fork).slice(0, 4).map((r) => r.name)))
      if (!res.repos.length) throw new Error('No public repositories found.')
    })

  const add = () =>
    run('Reading the repositories you picked…', async () => {
      const res = await api.githubImport(user(), [...picked])
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
          <button type="button" className="btn" style={{ alignSelf: 'flex-start' }} disabled={!picked.size || !!busy} onClick={add}>
            Use {picked.size} project{picked.size === 1 ? '' : 's'}
          </button>
        </>
      )}
      <p className="hint">Pasting your GitHub link above already adds your top repositories. Use this to pick different ones.</p>
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
      <button type="button" className="btn secondary" style={{ alignSelf: 'flex-start' }} disabled={!fact.trim()} onClick={add}>
        <Icon name="plus" /> Add fact
      </button>
      <p className="hint">Facts can back new bullets, including their numbers. Say where it happened so it lands under the right job.</p>
    </div>
  )
}
