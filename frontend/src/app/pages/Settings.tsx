import { useCallback, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api'
import { useAuth } from '../auth'
import { acct, type Links } from '../client'
import { ModelEditor, ResumeEditor, type ModelChoice } from '../editors'
import { Button, Card, Field, Icon, InfoTip, Notice, TextInput } from '../ui'

function Section({ title, info, children }: { title: string; info?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-space-md">
      <h2 className="flex items-center gap-2 font-headline-sm text-headline-sm text-on-surface">{title}{info && <InfoTip align="left">{info}</InfoTip>}</h2>
      <Card className="p-space-lg md:p-space-xl">{children}</Card>
    </section>
  )
}

export function Settings() {
  const { profile, setProfile, signOut } = useAuth()
  const navigate = useNavigate()
  const p = profile!
  const [toast, setToast] = useState<{ tone: 'good' | 'bad'; text: string } | null>(null)
  const say = useCallback((text: string, tone: 'good' | 'bad' = 'good') => {
    setToast({ tone, text })
    setTimeout(() => setToast(null), 3500)
  }, [])
  const fail = (e: unknown) => say(e instanceof ApiError || e instanceof Error ? e.message : 'Something went wrong.', 'bad')

  // profile
  const [f, setF] = useState({ full_name: p.details.full_name, headline: p.details.headline, location: p.details.location, phone: p.details.phone, public_email: p.details.public_email })
  const [links, setLinks] = useState<Links>(p.details.links)
  const [savingProfile, setSavingProfile] = useState(false)
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF((v) => ({ ...v, [k]: e.target.value }))
  const saveProfile = async () => {
    setSavingProfile(true)
    try {
      setProfile(await acct.saveDetails({ ...f, links }))
      say('Profile saved.')
    } catch (e) {
      fail(e)
    } finally {
      setSavingProfile(false)
    }
  }

  // resume
  const [tex, setTex] = useState(p.resume_tex)
  const [texOk, setTexOk] = useState(false)
  const [savingTex, setSavingTex] = useState(false)
  const saveTex = async () => {
    setSavingTex(true)
    try {
      await acct.saveResume(tex)
      setProfile(await acct.profile())
      say('Reference resume saved.')
    } catch (e) {
      fail(e)
    } finally {
      setSavingTex(false)
    }
  }

  // model
  const [choice, setChoice] = useState<ModelChoice>({ key: '', provider: null, model: '', ready: false })
  const [savingModel, setSavingModel] = useState(false)
  const [editorKey, setEditorKey] = useState(0)
  const changed = !!choice.key || (p.model.key_saved && !!choice.model && choice.model !== p.model.model)
  const saveModel = async () => {
    setSavingModel(true)
    try {
      await acct.saveModel(choice.key ? { provider: choice.provider, model: choice.model || null, key: choice.key } : { provider: p.model.provider, model: choice.model })
      setProfile(await acct.profile())
      setEditorKey((k) => k + 1)
      say('Model saved.')
    } catch (e) {
      fail(e)
    } finally {
      setSavingModel(false)
    }
  }
  const removeKey = async () => {
    if (!window.confirm('Remove your saved model key? You will need to add one to tailor resumes.')) return
    try {
      await acct.removeModel()
      setProfile(await acct.profile())
      setEditorKey((k) => k + 1)
      say('Key removed.')
    } catch (e) {
      fail(e)
    }
  }

  const deleteAccount = async () => {
    if (!window.confirm('Delete your account? This removes your profile, context and every saved resume. It cannot be undone.')) return
    try {
      await acct.deleteAccount()
      await signOut()
      navigate('/')
    } catch (e) {
      fail(e)
    }
  }

  return (
    <div className="mx-auto flex max-w-[760px] flex-col gap-space-xl">
      <h1 className="font-headline-lg-mobile text-headline-lg-mobile tracking-tight text-on-surface md:font-headline-lg md:text-headline-lg">Settings</h1>
      {toast && <div role="status" className="sticky top-20 z-30"><Notice tone={toast.tone}>{toast.text}</Notice></div>}

      <Section title="Profile" info="Used to name your files and personalize suggestions. We never change the contact details inside your LaTeX.">
        <div className="flex flex-col gap-space-md">
          <Field label="Full name"><TextInput value={f.full_name} onChange={set('full_name')} autoComplete="name" /></Field>
          <Field label="Headline"><TextInput value={f.headline} onChange={set('headline')} placeholder="Backend engineer" /></Field>
          <div className="grid grid-cols-1 gap-space-md md:grid-cols-2">
            <Field label="Location"><TextInput value={f.location} onChange={set('location')} /></Field>
            <Field label="Phone"><TextInput value={f.phone} onChange={set('phone')} autoComplete="tel" /></Field>
          </div>
          <Field label="Public email"><TextInput type="email" value={f.public_email} onChange={set('public_email')} /></Field>
          <div>
            <div className="mb-2 font-label-md text-label-md text-on-surface">Links</div>
            <div className="grid grid-cols-1 gap-space-sm md:grid-cols-3">
              <TextInput value={links.linkedin ?? ''} onChange={(e) => setLinks({ ...links, linkedin: e.target.value })} placeholder="linkedin.com/in/you" aria-label="LinkedIn link" />
              <TextInput value={links.github ?? ''} onChange={(e) => setLinks({ ...links, github: e.target.value })} placeholder="github.com/you" aria-label="GitHub link" />
              <TextInput value={links.portfolio ?? ''} onChange={(e) => setLinks({ ...links, portfolio: e.target.value })} placeholder="you.dev" aria-label="Portfolio link" />
            </div>
          </div>
          <div className="flex justify-end"><Button loading={savingProfile} disabled={!f.full_name.trim()} onClick={saveProfile}>Save profile</Button></div>
        </div>
      </Section>

      <Section title="Reference resume" info="Every tailored resume starts from this file. Only bullets, the summary and skills lines change.">
        <div className="flex flex-col gap-space-md">
          <ResumeEditor tex={tex} setTex={setTex} onValid={setTexOk} />
          <div className="flex justify-end"><Button loading={savingTex} disabled={!texOk || tex === p.resume_tex} onClick={saveTex}>Save resume</Button></div>
        </div>
      </Section>

      <Section title="AI model" info="Your key is stored encrypted in your account and used only for your requests. It is never shown again.">
        <div className="flex flex-col gap-space-md">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-surface-container-low px-4 py-3 font-body-md text-body-md">
            <span className="flex items-center gap-2">
              <Icon name="psychology" className="text-[20px] text-primary-container" />
              {p.model.key_saved ? <>{p.model.provider} · {p.model.model ?? 'recommended model'} · key {p.model.key_hint}</> : 'No key saved'}
            </span>
            {p.model.key_saved && <Button variant="danger" size="sm" onClick={removeKey}>Remove key</Button>}
          </div>
          <ModelEditor key={editorKey} saved={p.model} onChange={setChoice} />
          <div className="flex justify-end"><Button loading={savingModel} disabled={!changed || !choice.ready} onClick={saveModel}>Save model</Button></div>
        </div>
      </Section>

      <Section title="Account">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate font-label-md text-label-md text-on-surface">{p.account.demo ? 'Demo workspace' : p.account.email}</div>
            <div className="font-body-sm text-body-sm text-on-surface-variant">{p.account.demo ? 'Temporary, with a sample resume. Deleted two days after it was created.' : p.account.google && p.account.password ? 'Signed in with Google or a password' : p.account.google ? 'Signed in with Google' : 'Signed in with email and password'}</div>
          </div>
          <Button variant="secondary" onClick={async () => { await signOut(); navigate('/') }}>Sign out</Button>
        </div>
      </Section>

      <Section title="Danger zone">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-md font-body-md text-body-md text-on-surface-variant">Delete your account, and with it your profile, context, saved model key and every tailored resume.</p>
          <Button variant="danger" onClick={deleteAccount}><Icon name="delete_forever" className="text-[18px]" /> Delete my account</Button>
        </div>
      </Section>
    </div>
  )
}
