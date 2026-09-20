import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ApiError, api, streamTailor, type ProgressEvent, type Result } from '../../api'
import { useAuth } from '../auth'
import { acct } from '../client'
import { noteLines } from '../format'
import { sourceOf } from '../knowledge'
import { store } from '../storage'
import { ModelEditor, type ModelChoice } from '../editors'
import { Button, Card, Icon, InfoTip, Notice } from '../ui'

// The pipeline's own stages, grouped into the steps a person cares about.
const STEPS = [
  { id: 'resume', title: 'Reading your resume', stages: ['parse', 'compile_original'] },
  { id: 'job', title: 'Reading the job', stages: ['analyze'] },
  { id: 'match', title: 'Matching your background', stages: ['background', 'gaps', 'strategy'] },
  { id: 'plan', title: 'Planning edits', stages: ['plan'] },
  { id: 'check', title: 'Checking every edit', stages: ['validate'] },
  { id: 'build', title: 'Building the PDF', stages: ['compile', 'fit'] },
  { id: 'score', title: 'Scoring the result', stages: ['score', 'done'] },
] as const

type Stamped = ProgressEvent & { t: number }

export function NewResume() {
  const { profile, setProfile } = useAuth()
  const navigate = useNavigate()
  const start = (useLocation().state ?? {}) as { jd?: string; candidates?: 1 | 3 }
  const [jd, setJdState] = useState(() => start.jd ?? store.get('jd', ''))
  const setJd = (v: string) => {
    setJdState(v)
    store.set('jd', v)
  }
  const [candidates, setCandidates] = useState<1 | 3>(start.candidates ?? 1)
  const [limit, setLimit] = useState<number | null>(null)
  const [options, setOptions] = useState(true)
  const [running, setRunning] = useState(false)
  const [events, setEvents] = useState<Stamped[]>([])
  const [error, setError] = useState<string | null>(null)
  const [template, setTemplate] = useState<string | null>(null)
  const [context, setContext] = useState<{ count: number; chips: string[] }>({ count: 0, chips: [] })
  const [choice, setChoice] = useState<ModelChoice>({ key: '', provider: null, model: '', ready: false })
  const [savingKey, setSavingKey] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const started = useRef(0)

  useEffect(() => {
    let alive = true
    if (profile?.resume_tex) {
      api.parse(profile.resume_tex).then((o) => alive && setTemplate(`${{ jake: "Jake's Resume", 'awesome-cv': 'Awesome-CV', moderncv: 'moderncv', generic: 'Your template' }[o.profile] ?? 'Your template'} · ${o.stats.editable} editable blocks`)).catch(() => undefined)
    }
    acct.context().then((c) => {
      if (!alive) return
      const chips = c.entries.map((e) => (sourceOf(e) === 'github' && e.url ? e.url.replace(/^https?:\/\/github\.com\//, '') : sourceOf(e) === 'notes' ? (noteLines(e.text)[0] ?? e.text).slice(0, 28) : e.title).slice(0, 34))
      setContext({ count: c.entries.length, chips })
    }).catch(() => undefined)
    return () => {
      alive = false
    }
  }, [profile?.resume_tex])

  const words = jd.trim() ? jd.trim().split(/\s+/).length : 0
  const hasModel = !!profile?.model.key_saved
  const canRun = !!profile?.resume_tex.trim() && words >= 15 && !running

  const saveKey = async () => {
    setSavingKey(true)
    setError(null)
    try {
      await acct.saveModel({ provider: choice.provider, model: choice.model || null, key: choice.key })
      setProfile(await acct.profile())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the key.')
    } finally {
      setSavingKey(false)
    }
  }

  const run = async () => {
    abort.current?.abort()
    const ctrl = new AbortController()
    abort.current = ctrl
    setError(null)
    setEvents([])
    setRunning(true)
    started.current = performance.now()
    let result: Result | null = null
    try {
      await streamTailor(
        { jd, candidates, compile: true, page_limit: limit },
        (e) => {
          if (e.type === 'progress') setEvents((list) => [...list, { ...e, t: performance.now() }])
          else if (e.type === 'error') setError(e.message)
          else if (e.type === 'result') result = e
        },
        ctrl.signal,
        '/api/runs',
      )
      const done = result as (Result & { saved_run_id?: string }) | null
      if (done?.saved_run_id) navigate(`/runs/${done.saved_run_id}`)
      else if (done) setError('The resume was built but could not be saved to your history. Try again.')
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setError(e instanceof ApiError || e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="mx-auto max-w-[1040px]">
      <header className="mx-auto mb-space-xl max-w-[720px] text-center">
        <h1 className="mb-space-sm font-headline-lg-mobile text-headline-lg-mobile tracking-tight text-on-surface md:font-headline-lg md:text-headline-lg">Tailor for a new role</h1>
        <p className="mx-auto max-w-[620px] font-body-lg text-body-lg leading-relaxed text-on-surface-variant">Paste the job description. TailorTeX matches it against your resume and only uses facts from your context.</p>
      </header>

      {!profile?.resume_tex.trim() && <Notice tone="warn" className="mb-space-md">You haven't added your reference resume yet. <Link to="/settings" className="font-semibold underline">Add it in Settings</Link>.</Notice>}
      {profile?.resume_tex.trim() && !hasModel && (
        <Card className="mb-space-md p-space-lg">
          <div className="mb-space-sm flex items-center gap-2 font-headline-sm text-headline-sm text-on-surface">
            <Icon name="key" className="text-[20px] text-primary-container" /> Add your model key
            <InfoTip>TailorTeX uses your own key from Google Gemini, Groq, OpenAI, Anthropic, OpenRouter, Mistral or DeepSeek. It is stored encrypted in your account and only used for your requests. Gemini and Groq have free tiers. If this server provides its own key you can skip this.</InfoTip>
          </div>
          <ModelEditor saved={profile.model} onChange={setChoice} />
          <div className="mt-space-md flex justify-end"><Button loading={savingKey} disabled={!choice.ready || !choice.key} onClick={saveKey}>Save key</Button></div>
        </Card>
      )}

      <div className="grid grid-cols-1 items-start gap-space-xl lg:grid-cols-12">
        <section className="flex flex-col gap-space-lg lg:col-span-7">
          <Card className="flex flex-col p-space-lg">
            <div className="mb-space-sm flex items-center justify-between">
              <label htmlFor="job-desc" className="flex items-center gap-2 font-headline-sm text-headline-sm text-on-surface">
                <Icon name="content_paste_search" className="text-[20px] text-primary-container" /> Job description
              </label>
              <span className="rounded-full bg-surface-container-low px-2.5 py-1 font-code-sm text-code-sm text-on-surface-variant">Text or Markdown</span>
            </div>
            <div className="rounded-lg bg-surface-container-low p-space-sm transition-colors focus-within:bg-surface-container-lowest focus-within:ring-2 focus-within:ring-primary-container/20">
              <textarea
                id="job-desc"
                value={jd}
                onChange={(e) => setJd(e.target.value)}
                rows={11}
                placeholder="Paste the full job description here (responsibilities, requirements, qualifications)…"
                className="w-full resize-none border-0 bg-transparent p-space-xs font-body-md text-body-md leading-relaxed text-on-surface outline-none placeholder:text-outline"
              />
              <div className="mt-space-xs flex flex-wrap items-center justify-between gap-2 pt-space-sm text-on-surface-variant">
                <span className={`inline-flex items-center gap-1.5 font-code-sm text-code-sm ${words >= 15 ? 'text-primary' : ''}`}>
                  <Icon name={words >= 15 ? 'check_circle' : 'edit_note'} className="text-[15px]" />
                  {words ? `${words} words` : 'Waiting for the job description'}
                </span>
                <button type="button" onClick={() => setJd('')} className="rounded px-2 py-1 font-label-sm text-label-sm hover:bg-surface-container hover:text-on-surface">Clear text</button>
              </div>
            </div>

            <div className="mt-space-md rounded-lg bg-surface-container-low/60 p-space-md">
              <button type="button" aria-expanded={options} onClick={() => setOptions((o) => !o)} className="flex w-full items-center justify-between">
                <span className="flex items-center gap-2 font-label-md text-label-md font-semibold text-on-surface"><Icon name="tune" className="text-[18px] text-on-surface-variant" /> Options</span>
                <Icon name={options ? 'expand_less' : 'expand_more'} className="text-[18px] text-on-surface-variant" />
              </button>
              {options && (
                <div className="mt-space-md flex flex-col gap-space-md">
                  <div className="flex flex-col gap-1.5">
                    <div className="flex items-center gap-1 font-label-sm text-label-sm text-on-surface-variant">
                      Quality <InfoTip>Best of 3 tries three approaches and keeps the best. It uses about three times as many tokens.</InfoTip>
                    </div>
                    <Segmented
                      value={candidates}
                      onChange={setCandidates}
                      options={[{ value: 1, label: 'Fast' }, { value: 3, label: 'Best of 3' }]}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <div className="flex items-center gap-1 font-label-sm text-label-sm text-on-surface-variant">
                      Page limit <InfoTip>By default it keeps your resume's current length.</InfoTip>
                    </div>
                    <Segmented
                      value={limit}
                      onChange={setLimit}
                      options={[{ value: null, label: 'Same as my resume' }, { value: 1, label: '1 page' }, { value: 2, label: '2 pages' }]}
                    />
                  </div>
                  <div className="flex items-center justify-between rounded-lg bg-surface-container-lowest p-space-sm shadow-sm">
                    <div className="flex items-center gap-space-sm">
                      <div className="flex h-8 w-8 items-center justify-center rounded bg-primary-fixed"><Icon name="description" className="text-[18px] text-primary" /></div>
                      <div className="flex flex-col">
                        <span className="font-label-md text-label-md font-semibold text-on-surface">Your reference resume</span>
                        <span className="font-code-sm text-code-sm text-tertiary">{template ?? '…'}</span>
                      </div>
                    </div>
                    <Link to="/settings" className="font-label-sm text-label-sm text-primary hover:underline">Change</Link>
                  </div>
                </div>
              )}
            </div>

            <div className="flex flex-col items-center gap-space-md pt-space-lg sm:flex-row">
              {running ? (
                <Button size="lg" variant="secondary" className="w-full flex-1 sm:w-auto" onClick={() => abort.current?.abort()}>Cancel</Button>
              ) : (
                <Button size="lg" className="w-full flex-1 sm:w-auto" disabled={!canRun} onClick={run}><Icon name="bolt" className="text-[20px]" /> Tailor resume</Button>
              )}
              <Button size="lg" variant="ghost" className="w-full bg-surface-container sm:w-auto" disabled={running} onClick={async () => setJd((await api.sample()).jd)}>Load sample job</Button>
            </div>
            <div className="mt-space-sm flex items-center justify-between px-1 font-label-sm text-label-sm text-outline">
              <span className="flex items-center gap-1"><Icon name="verified_user" className="text-[14px] text-primary" /> Only your context is used</span>
              <span>Usually under a minute</span>
            </div>
          </Card>

          <Card className="p-space-md">
            <div className="mb-space-sm flex items-center justify-between">
              <span className="flex items-center gap-2 font-label-md text-label-md font-semibold text-on-surface"><Icon name="fact_check" className="text-[18px] text-tertiary" /> Your context</span>
              <Link to="/context" className="font-label-sm text-label-sm text-primary hover:underline">Manage context ({context.count} {context.count === 1 ? 'entry' : 'entries'})</Link>
            </div>
            {context.count === 0 ? (
              <p className="font-body-sm text-body-sm text-on-surface-variant">Nothing yet. Add your GitHub, portfolio or notes so TailorTeX can back new bullets. <Link to="/context" className="text-primary underline">Add context</Link></p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {context.chips.slice(0, 6).map((c, i) => (
                  <span key={i} className="flex items-center gap-1 rounded-full bg-surface-container-low px-2.5 py-1 font-code-sm text-[11px] text-on-surface-variant"><span className="h-1.5 w-1.5 rounded-full bg-primary-container" />{c}</span>
                ))}
                {context.count > 6 && <span className="rounded-full bg-surface-container px-2 py-1 font-code-sm text-[11px] text-tertiary">+{context.count - 6} more</span>}
              </div>
            )}
          </Card>
        </section>

        <section className="flex flex-col gap-space-md lg:col-span-5">
          <Pipeline events={events} running={running} error={error} />
        </section>
      </div>
    </div>
  )
}

function Segmented<T extends string | number | null>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[] }) {
  return (
    <div role="radiogroup" className="flex rounded-full bg-surface-container p-1 text-center">
      {options.map((o) => (
        <button
          key={String(o.value)}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={`flex-1 rounded-full px-2 py-1.5 font-label-md text-label-md transition-all ${value === o.value ? 'bg-surface-container-lowest font-semibold text-on-surface shadow-sm' : 'text-on-surface-variant hover:text-on-surface'}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Pipeline({ events, running, error }: { events: Stamped[]; running: boolean; error: string | null }) {
  const states = useMemo(() => {
    const idxOf = (stage: string) => STEPS.findIndex((s) => (s.stages as readonly string[]).includes(stage))
    const started: (number | null)[] = STEPS.map(() => null)
    const detail: string[] = STEPS.map(() => '')
    for (const e of events) {
      const i = idxOf(e.stage)
      if (i < 0) continue
      if (started[i] === null) started[i] = e.t
      detail[i] = e.message
    }
    const last = events.length ? idxOf(events[events.length - 1].stage) : -1
    return STEPS.map((s, i) => {
      const nextStart = started.slice(i + 1).find((t) => t !== null) ?? null
      const status: 'pending' | 'running' | 'done' = started[i] === null ? 'pending' : running && i === last && nextStart === null ? 'running' : 'done'
      const end = nextStart ?? (status === 'done' ? events[events.length - 1]?.t : null)
      return { ...s, status, detail: detail[i], seconds: started[i] !== null && end ? (end - (started[i] as number)) / 1000 : null }
    })
  }, [events, running])
  const done = states.filter((s) => s.status === 'done').length
  const active = events.length > 0
  const notice = [...events].reverse().find((e) => e.stage === 'model')?.message ?? null

  return (
    <Card className="p-space-lg">
      <div className="mb-space-md flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="relative flex h-3 w-3">
            {running && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary-container opacity-75" />}
            <span className={`relative inline-flex h-3 w-3 rounded-full ${running ? 'bg-primary' : active ? 'bg-emerald-500' : 'bg-outline-variant'}`} />
          </span>
          <span className="font-headline-sm text-headline-sm text-on-surface">{running ? 'Working' : active ? 'Finished' : 'What happens next'}</span>
        </div>
        {active && <span className="rounded-full bg-surface-container px-2.5 py-0.5 font-code-sm text-code-sm text-primary">{done} of {STEPS.length}</span>}
      </div>
      <div className="mb-space-lg h-1.5 w-full overflow-hidden rounded-full bg-surface-container">
        <div className="h-full rounded-full bg-primary-container transition-all duration-700 ease-out" style={{ width: `${(done / STEPS.length) * 100}%` }} />
      </div>
      <ol className="flex flex-col gap-3.5">
        {states.map((s, i) => (
          <li key={s.id} className={`flex items-start gap-space-sm ${s.status === 'running' ? '-mx-2.5 rounded-lg bg-surface-container/60 p-2.5' : ''}`}>
            <div className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${s.status === 'done' ? 'bg-surface-container text-primary' : s.status === 'running' ? 'bg-primary-container text-on-primary-container shadow-sm' : 'border border-outline-variant text-outline'}`}>
              {s.status === 'done' ? <Icon name="check" className="text-[16px]" /> : s.status === 'running' ? <Icon name="progress_activity" className="animate-spin text-[16px]" /> : <span className="font-code-sm text-[11px]">{i + 1}</span>}
            </div>
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex items-center justify-between gap-2">
                <span className={`truncate font-label-md text-label-md font-semibold ${s.status === 'pending' ? 'text-on-surface-variant' : s.status === 'running' ? 'text-primary' : 'text-on-surface'}`}>{s.title}</span>
                {s.seconds !== null && s.status === 'done' && <span className="font-code-sm text-code-sm text-tertiary">{s.seconds < 0.1 ? '<0.1' : s.seconds.toFixed(1)}s</span>}
                {s.status === 'running' && <span className="animate-pulse font-code-sm text-code-sm font-medium text-primary">Running</span>}
              </div>
              {s.detail && s.status !== 'pending' && <p className="line-clamp-2 font-body-sm text-body-sm text-on-surface-variant">{s.detail.replace(/^\[[^\]]*\]\s*/, '')}</p>}
            </div>
          </li>
        ))}
      </ol>
      {notice && running && <Notice tone="warn" icon="hourglass_top" className="mt-space-md">{notice}</Notice>}
      {error && <Notice tone="bad" className="mt-space-md">{error}</Notice>}
    </Card>
  )
}
