import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { ApiError, api, detectProvider, type Config, type ModelInfo, type Outline } from '../../api'
import { useAuth } from '../auth'
import { acct, type Links } from '../client'
import { EntryCard, LinkAdder, LinkedInAdder, NoteAdder, Status } from '../context'
import { useKnowledge } from '../knowledge'
import { Avatar, Badge, Button, Card, Field, Icon, InfoTip, Logo, Notice, Spinner, TextArea, TextInput } from '../ui'

const STEPS = ['about', 'resume', 'context', 'done'] as const
type Step = (typeof STEPS)[number]

export function Onboarding() {
  const { step } = useParams()
  if (!STEPS.includes(step as Step)) return <Navigate to="/onboarding/about" replace />
  return <Frame step={step as Step} />
}

function Frame({ step }: { step: Step }) {
  const { profile, signOut } = useAuth()
  const navigate = useNavigate()
  const n = STEPS.indexOf(step) + 1
  return (
    <div className="min-h-screen bg-surface-container-lowest">
      <header className="mx-auto flex h-16 max-w-[880px] items-center justify-between px-gutter-mobile md:px-gutter">
        <Logo />
        <div className="flex items-center gap-3">
          <Avatar name={profile?.details.full_name || profile?.account.email || ''} url={profile?.account.avatar_url} size={28} />
          <button type="button" onClick={async () => { await signOut(); navigate('/') }} className="font-label-sm text-label-sm text-on-surface-variant hover:text-on-surface">Sign out</button>
        </div>
      </header>
      <main className="mx-auto max-w-[880px] px-gutter-mobile pb-space-2xl pt-space-lg md:px-gutter">
        <div className="mb-space-xl">
          <div className="mb-2 flex items-center justify-between font-label-sm text-label-sm text-on-surface-variant">
            <span>Step {n} of {STEPS.length}</span>
            <span>{['About you', 'Resume and model', 'Your context', 'Done'][n - 1]}</span>
          </div>
          <div className="flex gap-1.5" role="progressbar" aria-valuemin={1} aria-valuemax={STEPS.length} aria-valuenow={n}>
            {STEPS.map((s, i) => (
              <div key={s} className={`h-1 flex-1 rounded-full ${i < n ? 'bg-primary-container' : 'bg-surface-variant'}`} />
            ))}
          </div>
        </div>
        {step === 'about' && <About />}
        {step === 'resume' && <ResumeAndModel />}
        {step === 'context' && <ContextStep />}
        {step === 'done' && <Done />}
      </main>
    </div>
  )
}

function Heading({ title, info, sub }: { title: string; info?: ReactNode; sub?: string }) {
  return (
    <div className="mb-space-lg">
      <h1 className="flex items-center gap-2 font-headline-lg-mobile text-headline-lg-mobile tracking-tight text-on-surface md:font-headline-md md:text-headline-md">
        {title}
        {info && <InfoTip align="left">{info}</InfoTip>}
      </h1>
      {sub && <p className="mt-1 font-body-md text-body-md text-on-surface-variant">{sub}</p>}
    </div>
  )
}

// --- 1. about you ------------------------------------------------------------------------------------------

function About() {
  const { profile, setProfile } = useAuth()
  const navigate = useNavigate()
  const d = profile!.details
  const [f, setF] = useState({ full_name: d.full_name, headline: d.headline, location: d.location, phone: d.phone, public_email: d.public_email || profile!.account.email || '' })
  const [links, setLinks] = useState<Links>(d.links)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF((v) => ({ ...v, [k]: e.target.value }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      setProfile(await acct.saveDetails({ ...f, links }))
      navigate('/onboarding/resume')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit}>
      <Heading title="About you" info="Used to name your files and personalize suggestions. We never change the contact details inside your LaTeX." />
      <Card className="flex flex-col gap-space-md p-space-lg md:p-space-xl">
        <Field label="Full name">
          <TextInput required value={f.full_name} onChange={set('full_name')} autoComplete="name" placeholder="Aarav Mehta" />
        </Field>
        <Field label="Headline">
          <TextInput value={f.headline} onChange={set('headline')} placeholder="Backend engineer" />
        </Field>
        <div className="grid grid-cols-1 gap-space-md md:grid-cols-2">
          <Field label="Location">
            <TextInput value={f.location} onChange={set('location')} autoComplete="address-level2" placeholder="Bengaluru, India" />
          </Field>
          <Field label="Phone">
            <TextInput value={f.phone} onChange={set('phone')} autoComplete="tel" placeholder="+91 98765 43210" />
          </Field>
        </div>
        <Field label="Public email">
          <TextInput type="email" value={f.public_email} onChange={set('public_email')} autoComplete="email" />
        </Field>
        <div className="mt-1">
          <div className="mb-2 flex items-center gap-1 font-label-md text-label-md text-on-surface">
            Links <InfoTip>We read GitHub and your portfolio in a later step. LinkedIn works differently; you'll see why there.</InfoTip>
          </div>
          <div className="grid grid-cols-1 gap-space-sm md:grid-cols-3">
            <TextInput value={links.linkedin ?? ''} onChange={(e) => setLinks({ ...links, linkedin: e.target.value })} placeholder="linkedin.com/in/you" aria-label="LinkedIn link" />
            <TextInput value={links.github ?? ''} onChange={(e) => setLinks({ ...links, github: e.target.value })} placeholder="github.com/you" aria-label="GitHub link" />
            <TextInput value={links.portfolio ?? ''} onChange={(e) => setLinks({ ...links, portfolio: e.target.value })} placeholder="you.dev" aria-label="Portfolio link" />
          </div>
        </div>
        {error && <Notice tone="bad">{error}</Notice>}
        <div className="flex justify-end pt-2">
          <Button type="submit" size="lg" loading={busy} disabled={!f.full_name.trim()}>Continue <Icon name="arrow_forward" className="text-[18px]" /></Button>
        </div>
      </Card>
    </form>
  )
}

// --- 2. resume and model ------------------------------------------------------------------------------------

function ResumeAndModel() {
  const { profile, setProfile } = useAuth()
  const navigate = useNavigate()
  const [tex, setTex] = useState(profile!.resume_tex)
  const [outline, setOutline] = useState<{ tex: string; outline: Outline | null; error: string | null } | null>(null)
  const [showOutline, setShowOutline] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!tex.trim()) return
    const t = setTimeout(() => {
      api.parse(tex).then((o) => setOutline({ tex, outline: o, error: o.stats.sections === 0 ? 'No sections found. TailorTeX needs \\section{…} headings.' : null })).catch((e: Error) => setOutline({ tex, outline: null, error: e.message }))
    }, 350)
    return () => clearTimeout(t)
  }, [tex])
  const parsed = tex.trim() && outline?.tex === tex ? outline : null
  const ok = !!parsed?.outline && !parsed.error && parsed.outline.stats.editable > 0

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
  const fix = async (id: string) => {
    const r = await api.lintFix(tex, id)
    setTex(r.tex)
  }

  // model
  const [config, setConfig] = useState<Config | null>(null)
  const [key, setKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [providerPick, setProviderPick] = useState<string | null>(null)
  const [models, setModels] = useState<ModelInfo[]>([])
  const [model, setModel] = useState(profile!.model.model ?? '')
  const [check, setCheck] = useState<{ kind: 'idle' | 'loading' | 'ok' | 'error'; text?: string }>({ kind: 'idle' })
  const saved = profile!.model
  const provider = providerPick ?? detectProvider(key) ?? saved.provider
  useEffect(() => {
    void api.config().then(setConfig).catch(() => undefined)
  }, [])
  useEffect(() => {
    const k = key.trim()
    if (!k) return
    if (!provider) return
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
  const keyOk = check.kind === 'ok' || (!key.trim() && saved.key_saved)
  const needsProvider = key.trim().length > 10 && !provider

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const next = async () => {
    setBusy(true)
    setError(null)
    try {
      await acct.saveResume(tex)
      if (key.trim()) await acct.saveModel({ provider, model: model || null, key: key.trim() })
      else if (saved.key_saved && model && model !== saved.model) await acct.saveModel({ provider: saved.provider, model })
      setProfile(await acct.profile())
      navigate('/onboarding/context')
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : 'Could not save.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-space-lg">
      <Heading title="Your resume" info="Only bullets, the summary and skills lines change. Education, headers and everything else stay exactly as written." />
      <Card className="flex flex-col gap-space-md p-space-lg md:p-space-xl">
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
          placeholder={'Paste your resume\'s LaTeX, from \\documentclass to \\end{document}'}
          className="font-code-md text-code-md"
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" onClick={pasteClipboard}><Icon name="content_paste" className="text-[18px]" /> Paste from clipboard</Button>
          <Button variant="ghost" size="sm" onClick={() => fileRef.current?.click()}><Icon name="upload_file" className="text-[18px]" /> Upload .tex</Button>
          {!tex.trim() && (
            <Button variant="ghost" size="sm" onClick={async () => setTex((await api.template()).tex)}>Start from our template</Button>
          )}
          <input ref={fileRef} type="file" accept=".tex,.txt" hidden onChange={(e) => { void upload(e.target.files?.[0]); e.target.value = '' }} />
        </div>
        {message && <Notice tone="warn">{message}</Notice>}
        {tex.trim() && !parsed && <div className="flex items-center gap-2 font-body-sm text-body-sm text-on-surface-variant"><Spinner /> Reading your resume…</div>}
        {parsed?.error && <Notice tone="bad">{parsed.error}</Notice>}
        {parsed?.outline && !parsed.error && (
          <div className="rounded-xl bg-surface-container-low p-space-md">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="good"><Icon name="check_circle" fill className="text-[16px]" /> Recognized</Badge>
              <Badge>{{ jake: "Jake's Resume", 'awesome-cv': 'Awesome-CV', moderncv: 'moderncv', generic: 'Custom template' }[parsed.outline.profile] ?? parsed.outline.profile}</Badge>
              <span className="font-body-sm text-body-sm text-on-surface">
                {parsed.outline.stats.sections} sections · {parsed.outline.stats.bullets} bullets · {parsed.outline.stats.editable} editable
              </span>
              <button type="button" onClick={() => setShowOutline((s) => !s)} className="font-label-sm text-label-sm text-primary hover:underline">
                {showOutline ? 'Hide' : 'Show'} what we see
              </button>
            </div>
            {showOutline && (
              <div className="mt-3 max-h-72 overflow-auto rounded-lg bg-surface-container-lowest p-3 font-code-sm text-code-sm">
                {parsed.outline.sections.map((s) => (
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
        {parsed?.outline?.lint.filter((l) => l.severity === 'warn').map((w) => (
          <Notice key={w.id} tone="warn">
            <div className="flex flex-wrap items-center justify-between gap-2"><span>{w.message}</span>{w.fixable && <Button size="sm" variant="secondary" onClick={() => fix(w.id)}>Fix it</Button>}</div>
          </Notice>
        ))}
      </Card>

      <Heading title="AI model" info="Your key is stored encrypted in your account and used only for your requests. You can remove it any time in Settings." />
      <Card className="flex flex-col gap-space-md p-space-lg md:p-space-xl">
        {saved.key_saved && !key.trim() && (
          <Notice tone="good">A key is already saved ({saved.key_hint}) for {saved.provider}. Paste a new one to replace it.</Notice>
        )}
        <Field label="API key" hint={config ? undefined : undefined}>
          <div className="flex gap-2">
            <TextInput type={showKey ? 'text' : 'password'} value={key} onChange={(e) => setKey(e.target.value)} placeholder="Paste a key: AIza…, gsk_…, sk-…, sk-ant-…, sk-or-…" autoComplete="off" spellCheck={false} />
            <Button variant="ghost" onClick={() => setShowKey((s) => !s)}>{showKey ? 'Hide' : 'Show'}</Button>
          </div>
        </Field>
        {needsProvider && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-body-sm text-body-sm text-on-surface-variant">Which provider?</span>
            {config?.providers.map((p) => (
              <button key={p.id} type="button" onClick={() => setProviderPick(p.id)} className={`rounded-full border px-3 py-1 font-label-sm text-label-sm ${providerPick === p.id ? 'border-primary-container bg-primary-fixed/40 text-primary' : 'border-outline-variant text-on-surface-variant hover:bg-surface-container-low'}`}>{p.label}</button>
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
      </Card>
      {error && <Notice tone="bad">{error}</Notice>}
      <div className="flex items-center justify-between">
        <Link to="/onboarding/about" className="font-label-md text-label-md text-on-surface-variant hover:text-on-surface">Back</Link>
        <Button size="lg" loading={busy} disabled={!ok || !keyOk} onClick={next}>Continue <Icon name="arrow_forward" className="text-[18px]" /></Button>
      </div>
    </div>
  )
}

// --- 3. context ---------------------------------------------------------------------------------------------

function ContextStep() {
  const { setProfile } = useAuth()
  const navigate = useNavigate()
  const k = useKnowledge()
  const [busy, setBusy] = useState(false)
  const finish = useCallback(async () => {
    setBusy(true)
    try {
      setProfile(await acct.saveDetails({ onboarded: true }))
      navigate('/onboarding/done')
    } catch (e) {
      k.setError(e instanceof Error ? e.message : 'Could not finish.')
    } finally {
      setBusy(false)
    }
  }, [setProfile, navigate, k])

  return (
    <div className="flex flex-col gap-space-lg">
      <Heading title="Build your context" info="This is your private knowledge base. When you tailor a resume, TailorTeX finds the parts of it that fit the job, and only adds what's backed here." sub="Everything is optional. The more you add, the more it can back." />
      <div className="grid grid-cols-1 gap-space-md md:grid-cols-2">
        <Card className="flex flex-col gap-3 p-space-lg">
          <SourceTitle icon="terminal" title="GitHub" />
          <LinkAdder kind="github" k={k} />
        </Card>
        <Card className="flex flex-col gap-3 p-space-lg">
          <SourceTitle icon="language" title="Portfolio" />
          <LinkAdder kind="portfolio" k={k} />
        </Card>
        <Card className="flex flex-col gap-3 p-space-lg">
          <SourceTitle icon="description" title="LinkedIn" info="LinkedIn doesn't let apps read profiles from a link, so its own PDF export is the reliable way. On your profile, click More, then Save to PDF. It's read once and not stored." />
          <LinkedInAdder k={k} />
        </Card>
        <Card className="flex flex-col gap-3 p-space-lg">
          <SourceTitle icon="edit_note" title="Anything else" info="Say where something happened so it lands under the right job. Numbers are used exactly as you write them." />
          <NoteAdder k={k} rows={4} />
        </Card>
      </div>
      <Status k={k} />
      {k.entries.length > 0 && (
        <div>
          <div className="mb-2 font-label-md text-label-md text-on-surface-variant">{k.entries.length} {k.entries.length === 1 ? 'entry' : 'entries'} so far</div>
          <div className="grid grid-cols-1 gap-space-md md:grid-cols-2">
            {k.entries.slice(0, 6).map((e) => <EntryCard key={e.id} entry={e} busy={!!k.busy} onEdit={(c) => k.editEntry(e, c)} onDelete={() => void k.removeEntry(e)} />)}
          </div>
          {k.entries.length > 6 && <p className="mt-2 font-body-sm text-body-sm text-on-surface-variant">and {k.entries.length - 6} more. You can manage everything under “My context”.</p>}
        </div>
      )}
      <div className="flex items-center justify-between">
        <Link to="/onboarding/resume" className="font-label-md text-label-md text-on-surface-variant hover:text-on-surface">Back</Link>
        <div className="flex items-center gap-2">
          {k.entries.length === 0 && <Button variant="ghost" onClick={finish} disabled={busy}>I'll do this later</Button>}
          <Button size="lg" loading={busy} onClick={finish}>Finish setup <Icon name="arrow_forward" className="text-[18px]" /></Button>
        </div>
      </div>
    </div>
  )
}

function SourceTitle({ icon, title, info }: { icon: string; title: string; info?: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-container"><Icon name={icon} className="text-[18px] text-primary-container" /></span>
      <span className="font-label-md text-label-md font-semibold text-on-surface">{title}</span>
      {info && <InfoTip>{info}</InfoTip>}
    </div>
  )
}

// --- 4. done ------------------------------------------------------------------------------------------------

function Done() {
  const { profile } = useAuth()
  const [editable, setEditable] = useState<number | null>(null)
  useEffect(() => {
    if (profile?.resume_tex) void api.parse(profile.resume_tex).then((o) => setEditable(o.stats.editable)).catch(() => undefined)
  }, [profile?.resume_tex])
  const entries = Object.values(profile?.context_counts ?? {}).reduce((a, b) => a + b, 0)
  const model = profile?.model
  return (
    <div className="flex flex-col items-center gap-space-lg py-space-xl text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50"><Icon name="check" className="text-[32px] text-emerald-600" /></span>
      <div>
        <h1 className="font-headline-lg-mobile text-headline-lg-mobile tracking-tight text-on-surface md:font-headline-lg md:text-headline-lg">You're set up</h1>
        <p className="mt-1 font-body-md text-body-md text-on-surface-variant">Paste a job description and get your first tailored resume.</p>
      </div>
      <div className="grid w-full max-w-xl grid-cols-1 gap-space-sm sm:grid-cols-3">
        <Tile label="Resume" value={editable === null ? '…' : `${editable} editable`} />
        <Tile label="Context" value={`${entries} ${entries === 1 ? 'entry' : 'entries'}`} />
        <Tile label="Model" value={model?.model ?? model?.provider ?? '–'} />
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        <Link to="/new" className="inline-flex items-center gap-1.5 rounded-full bg-primary-container px-7 py-3.5 font-label-md text-label-md font-semibold text-on-primary-container shadow-sm hover:bg-primary">Tailor my first resume</Link>
        <Link to="/dashboard" className="inline-flex items-center gap-1.5 rounded-full border border-outline-variant px-7 py-3.5 font-label-md text-label-md font-semibold text-on-surface hover:bg-surface-container-low">Go to dashboard</Link>
      </div>
    </div>
  )
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-surface-container-low p-4 text-left">
      <div className="font-label-sm text-label-sm uppercase tracking-wider text-on-surface-variant">{label}</div>
      <div className="mt-1 truncate font-headline-sm text-headline-sm text-on-surface" title={value}>{value}</div>
    </div>
  )
}
