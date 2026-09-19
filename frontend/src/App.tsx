import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, streamTailor, type Config, type Evidence, type Outline, type ProgressEvent, type Result } from './api'
import type { Decision } from './components/ChangeCard'
import { EvidenceCard } from './components/EvidenceCard'
import { Icon, Spinner } from './components/Icons'
import { JobCard } from './components/JobCard'
import { ModelCard } from './components/ModelCard'
import { Progress } from './components/Progress'
import { ResumeCard } from './components/ResumeCard'
import { Results, type View } from './components/Results'
import { base64ToBlob, deviceId, downloadBlob, openInOverleaf, plain, store } from './util'

const REPO_URL = 'https://github.com/shreytiwari09/TailorTex'

const signature = (d: Record<number, Decision>) =>
  JSON.stringify(Object.entries(d).filter(([, v]) => v.action !== 'kept').sort(([a], [b]) => Number(a) - Number(b)))

export default function App() {
  const [config, setConfig] = useState<Config | null>(null)
  const [configError, setConfigError] = useState<string | null>(null)

  const [remember, setRemember] = useState(() => store.get('remember', false))
  const [apiKey, setApiKey] = useState(() => (store.get('remember', false) ? store.get('key', '') : ''))
  const [provider, setProvider] = useState<string | null>(null)
  const [model, setModel] = useState(() => store.get('model', ''))

  const [tex, setTex] = useState(() => store.get('tex', ''))
  const [parsed, setParsed] = useState<{ tex: string; outline: Outline | null; error: string | null } | null>(null)

  const [evidence, setEvidence] = useState<Evidence[]>(() => store.get('evidence', []))
  const [skills, setSkills] = useState<string[]>(() => store.get('skills', []))
  const [jd, setJd] = useState(() => store.get('jd', ''))
  const [candidates, setCandidates] = useState(() => store.get('candidates', 1))
  const [compilePdf, setCompilePdf] = useState(true)
  const [pageLimit, setPageLimit] = useState<number | null>(null)

  const [running, setRunning] = useState(false)
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [runModel, setRunModel] = useState<string | null>(null)
  const [result, setResult] = useState<Result | null>(null)
  const [view, setView] = useState<View | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [decisions, setDecisions] = useState<Record<number, Decision>>({})
  const [built, setBuilt] = useState('[]')
  const [rebuilding, setRebuilding] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const feedbackSent = useRef<string | null>(null)
  const resultsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.config().then(setConfig).catch((e: Error) => setConfigError(e.message))
  }, [])

  // Keep inputs across reloads. The key is kept only when the user asks.
  useEffect(() => store.set('tex', tex), [tex])
  useEffect(() => store.set('jd', jd), [jd])
  useEffect(() => store.set('evidence', evidence), [evidence])
  useEffect(() => store.set('skills', skills), [skills])
  useEffect(() => store.set('model', model), [model])
  useEffect(() => store.set('candidates', candidates), [candidates])
  useEffect(() => {
    store.set('remember', remember)
    if (remember) store.set('key', apiKey)
    else store.remove('key')
  }, [remember, apiKey])

  // Parse the resume as it changes, to show what TailorTeX sees.
  useEffect(() => {
    if (!tex.trim()) return
    const t = setTimeout(() => {
      api
        .parse(tex)
        .then((o) => setParsed({ tex, outline: o, error: o.stats.sections === 0 ? 'No sections found. TailorTeX needs \\section{…} headings.' : null }))
        .catch((e: Error) => setParsed({ tex, outline: null, error: e.message }))
    }, 400)
    return () => clearTimeout(t)
  }, [tex])
  const hasTex = !!tex.trim()
  const outline = hasTex ? parsed?.outline ?? null : null
  const parseError = hasTex ? parsed?.error ?? null : null
  const parsing = hasTex && parsed?.tex !== tex

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(t)
  }, [toast])

  const loadSample = async () => {
    try {
      const s = await api.sample()
      setTex(s.tex)
      setJd(s.jd)
      setEvidence(s.evidence)
      setSkills(s.skills)
      setToast('Sample loaded: a resume, a job description and some evidence. Add a model key and press Tailor.')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const loadTemplate = async () => {
    try {
      setTex((await api.template()).tex)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const fixLint = async (fix: string) => {
    try {
      const r = await api.lintFix(tex, fix)
      setTex(r.tex)
      setToast('Fixed. The two lines were added to your preamble.')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const hasModel = !!apiKey.trim() || !!config?.server_key
  const blockers = [
    !hasModel && 'add a model key (step 1)',
    !tex.trim() && 'add your resume (step 2)',
    outline && outline.stats.editable === 0 && 'use a resume with bullets TailorTeX can edit',
    !jd.trim() && 'paste the job description (step 4)',
  ].filter(Boolean) as string[]

  const run = async () => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setError(null)
    setResult(null)
    setView(null)
    setEvents([])
    setDecisions({})
    setBuilt('[]')
    setRunning(true)
    feedbackSent.current = null
    try {
      await streamTailor(
        {
          tex,
          jd,
          key: apiKey.trim() || null,
          provider: apiKey.trim() ? provider : null,
          model: model || null,
          evidence,
          skills,
          candidates,
          compile: compilePdf,
          page_limit: pageLimit,
          user: deviceId(),
        },
        (e) => {
          if (e.type === 'progress') setEvents((ev) => [...ev, e])
          else if (e.type === 'start') setRunModel(e.model)
          else if (e.type === 'error') setError(e.message)
          else if (e.type === 'result') {
            setResult(e)
            setView({ tex: e.tex, pdf: e.pdf, after: e.after, warnings: e.warnings })
            setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
          }
        },
        ctrl.signal,
      )
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  const sendFeedback = useCallback(() => {
    if (!result) return
    const sig = `${result.run_id}:${signature(decisions)}`
    if (feedbackSent.current === sig) return
    feedbackSent.current = sig
    api
      .feedback({
        run_id: result.run_id,
        context: result.context,
        arm: result.arm,
        reward: result.reward,
        user: deviceId(),
        key: apiKey.trim() || null,
        provider: apiKey.trim() ? provider : null,
        model: model || null,
        decisions: result.changes.map((c) => ({
          change_id: c.id,
          action: decisions[c.id]?.action ?? 'kept',
          suggested: plain(c.after).slice(0, 2000),
          final: (decisions[c.id]?.text ?? '').slice(0, 2000),
        })),
      })
      .then((r) => {
        if (r.style_rules?.length) setToast(`Learned your style: ${r.style_rules.slice(0, 2).join('; ')}`)
      })
      .catch(() => {
        /* feedback is best-effort */
      })
  }, [result, decisions, apiKey, provider, model])

  const rebuild = async () => {
    if (!result) return
    setRebuilding(true)
    setError(null)
    try {
      const ops = result.ops.flatMap((op, i) => {
        const d = decisions[i]
        if (d?.action === 'reverted') return []
        if (d?.action === 'edited') return [{ ...op, text: d.text ?? op.text, source: 'user' as const }]
        return [op]
      })
      const r = await api.rebuild({ tex, ops, analysis: result.analysis, evidence, skills, compile: compilePdf, page_limit: result.page_limit })
      setView({ tex: r.tex, pdf: r.pdf, after: r.after, warnings: r.warnings })
      setBuilt(signature(decisions))
      sendFeedback()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRebuilding(false)
    }
  }

  const evidenceLabels = useMemo(() => {
    const m: Record<string, string> = { skills: 'skills you confirmed' }
    for (const e of evidence) m[e.id] = e.title || e.id
    return m
  }, [evidence])

  const confirmSkill = (term: string) => {
    if (!skills.some((s) => s.toLowerCase() === term.toLowerCase())) setSkills([...skills, term])
    setToast(`Added "${term}" to the skills you can defend. Run again to use it.`)
  }

  const dirty = !!result && signature(decisions) !== built
  const filename = result?.filename ?? 'resume'

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="/">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          <span>TailorTeX</span>
        </a>
        <nav className="row gap-s">
          <a className="btn ghost small" href="/docs" target="_blank" rel="noreferrer">API</a>
          <a className="btn ghost small" href={REPO_URL} target="_blank" rel="noreferrer">
            <Icon name="github" /> GitHub
          </a>
        </nav>
      </header>

      <main>
        <section className="hero">
          <h1>Tailor your LaTeX resume to every job, without inventing anything.</h1>
          <p className="lead">
            Paste a job description and get back your own template with the right keywords in the right places. It compiles every time, and every new
            skill or number is checked against your real experience.
          </p>
          <div className="row wrap gap-s center">
            <button type="button" className="btn big" onClick={loadSample}>
              <Icon name="play" /> Try it with a sample resume
            </button>
            <a className="btn ghost big" href="#how">How it works</a>
          </div>
          <ul className="promises">
            <li><Icon name="file" /> Your template stays byte-for-byte intact</li>
            <li><Icon name="check" /> Always compiles: the model never writes LaTeX</li>
            <li><Icon name="shield" /> Never invents skills, employers or numbers</li>
            <li><Icon name="target" /> Honest ATS checks on the real PDF text</li>
          </ul>
        </section>

        {configError && (
          <div className="note warn-note wide">
            <Icon name="alert" /> {configError}
          </div>
        )}

        <div className="layout">
          <div className="col inputs">
            <ModelCard
              config={config}
              apiKey={apiKey}
              setApiKey={setApiKey}
              provider={provider}
              setProvider={setProvider}
              model={model}
              setModel={setModel}
              remember={remember}
              setRemember={setRemember}
            />
            <ResumeCard tex={tex} setTex={setTex} outline={outline} parsing={parsing} parseError={parseError} onFix={fixLint} onTemplate={loadTemplate} />
            <EvidenceCard evidence={evidence} setEvidence={setEvidence} skills={skills} setSkills={setSkills} />
            <JobCard
              jd={jd}
              setJd={setJd}
              candidates={candidates}
              setCandidates={setCandidates}
              compilePdf={compilePdf}
              setCompilePdf={setCompilePdf}
              pageLimit={pageLimit}
              setPageLimit={setPageLimit}
              texAvailable={config?.tex ?? true}
            />
            <div className="run-bar">
              {running ? (
                <button type="button" className="btn big secondary full" onClick={() => abortRef.current?.abort()}>
                  <Spinner /> Tailoring… (cancel)
                </button>
              ) : (
                <button type="button" className="btn big full" disabled={blockers.length > 0} onClick={run}>
                  <Icon name="wand" /> Tailor my resume
                </button>
              )}
              {blockers.length > 0 && !running && <p className="hint center">To start, {blockers.join(', ')}.</p>}
            </div>
          </div>

          <div className="col output" ref={resultsRef}>
            {error && (
              <div className="note bad-note">
                <Icon name="alert" /> <span>{error}</span>
              </div>
            )}
            {events.length > 0 && <Progress events={events} running={running} model={runModel} />}
            {result && view && (
              <Results
                result={result}
                view={view}
                decisions={decisions}
                setDecision={(id, d) => setDecisions((prev) => ({ ...prev, [id]: d }))}
                dirty={dirty}
                rebuilding={rebuilding}
                onRebuild={rebuild}
                evidenceLabels={evidenceLabels}
                skills={skills}
                onConfirmSkill={confirmSkill}
                onDownloadPdf={() => {
                  if (view.pdf) downloadBlob(base64ToBlob(view.pdf, 'application/pdf'), `${filename}.pdf`)
                  sendFeedback()
                }}
                onDownloadTex={() => {
                  downloadBlob(new Blob([view.tex], { type: 'application/x-tex' }), `${filename}.tex`)
                  sendFeedback()
                }}
                onCopy={async () => {
                  try {
                    await navigator.clipboard.writeText(view.tex)
                  } catch {
                    setError("Couldn't copy to the clipboard. Use the LaTeX tab instead.")
                  }
                  sendFeedback()
                }}
                onOverleaf={() => {
                  openInOverleaf(view.tex, `${filename}.tex`, result.engine)
                  sendFeedback()
                }}
              />
            )}
            {!events.length && !result && <HowItWorks />}
          </div>
        </div>
      </main>

      <footer className="footer">
        <span>TailorTeX · built for HackDevengers 2.0 · your keys and resume go only to the model provider you choose</span>
        <a href={REPO_URL} target="_blank" rel="noreferrer">Source on GitHub</a>
      </footer>

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  )
}

function HowItWorks() {
  const steps = [
    { icon: 'layers', title: 'Parse', text: 'Your .tex is split into sections, entries, bullets and skills lines, each with its exact position. Education and similar sections are locked.' },
    { icon: 'briefcase', title: 'Read the job', text: 'Your model pulls out the title and the must-have and nice-to-have keywords, then each keyword is matched against your resume and evidence.' },
    { icon: 'pencil', title: 'Plan edits', text: 'The model proposes edit operations in plain text (rewrite, add, reorder), never a new .tex file, so it can’t break your template.' },
    { icon: 'shield', title: 'Guardrails', text: 'Code checks every edit: no skill, name or number that your resume or evidence doesn’t support. Rejected edits go back to the model with the reason.' },
    { icon: 'target', title: 'Compile and check', text: 'TailorTeX writes the LaTeX itself, compiles it, fits it to your page limit, and measures keyword coverage and ATS parse health on the real PDF text.' },
  ] as const
  return (
    <section className="card how" id="how">
      <h2>How it works</h2>
      <ol className="how-steps">
        {steps.map((s) => (
          <li key={s.title}>
            <span className="how-icon"><Icon name={s.icon} /></span>
            <div>
              <strong>{s.title}</strong>
              <p className="muted">{s.text}</p>
            </div>
          </li>
        ))}
      </ol>
      <div className="note info-note">
        <Icon name="info" />
        <span>
          It learns as you use it: every change you keep, revert or edit teaches it which tailoring strategy works for which kind of job, and which
          writing style you prefer.
        </span>
      </div>
    </section>
  )
}
