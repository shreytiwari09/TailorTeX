import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { ApiError, api } from '../../api'
import { useAuth } from '../auth'
import { acct, type Links } from '../client'
import { EntryCard, LinkAdder, LinkedInAdder, NoteAdder, RepoPicker, Status } from '../context'
import { ModelEditor, ResumeEditor, type ModelChoice } from '../editors'
import { useKnowledge } from '../knowledge'
import { Avatar, Button, Card, Field, Icon, InfoTip, Logo, Notice, TextInput } from '../ui'

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
  const [ok, setOk] = useState(false)
  const [choice, setChoice] = useState<ModelChoice>({ key: '', provider: null, model: '', ready: false })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const saved = profile!.model

  const next = async () => {
    setBusy(true)
    setError(null)
    try {
      await acct.saveResume(tex)
      if (choice.key) await acct.saveModel({ provider: choice.provider, model: choice.model || null, key: choice.key })
      else if (saved.key_saved && choice.model && choice.model !== saved.model) await acct.saveModel({ provider: saved.provider, model: choice.model })
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
      <Card className="p-space-lg md:p-space-xl"><ResumeEditor tex={tex} setTex={setTex} onValid={setOk} /></Card>
      <Heading title="AI model" info="Your key is stored encrypted in your account and used only for your requests. You can remove it any time in Settings." />
      <Card className="p-space-lg md:p-space-xl"><ModelEditor saved={saved} onChange={setChoice} /></Card>
      {error && <Notice tone="bad">{error}</Notice>}
      <div className="flex items-center justify-between">
        <Link to="/onboarding/about" className="font-label-md text-label-md text-on-surface-variant hover:text-on-surface">Back</Link>
        <Button size="lg" loading={busy} disabled={!ok || !choice.ready} onClick={next}>Continue <Icon name="arrow_forward" className="text-[18px]" /></Button>
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
      <RepoPicker k={k} />
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
