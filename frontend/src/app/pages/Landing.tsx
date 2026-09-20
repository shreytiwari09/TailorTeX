import { Suspense, lazy, useCallback, useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { ApiError } from '../../api'
import { useAuth } from '../auth'
import { GoogleButton } from '../GoogleButton'
import { Badge, Button, Icon, InfoTip, Logo, Notice, Skeleton } from '../ui'

const FirebaseSignIn = lazy(() => import('../FirebaseSignIn')) // the Firebase SDK is only loaded when sign-in goes through it

export function Landing() {
  const auth = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'signup' | 'signin'>('signup')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [demoBusy, setDemoBusy] = useState(false)

  const after = useCallback(
    (onboarded: boolean) => navigate(onboarded ? '/dashboard' : '/onboarding/about', { replace: true }),
    [navigate],
  )
  const fail = useCallback((e: unknown) => setError(e instanceof ApiError || e instanceof Error ? e.message : 'Something went wrong.'), [])
  const google = useCallback(
    (credential: string) => {
      setError(null)
      auth.signInGoogle(credential).then((p) => after(p.onboarded)).catch(fail)
    },
    [auth, after, fail],
  )

  const demo = async () => {
    setDemoBusy(true)
    setError(null)
    try {
      const { jd } = await auth.startDemo()
      navigate('/new', { state: { jd } })
    } catch (err) {
      setDemoBusy(false)
      fail(err)
    }
  }

  const firebaseIn = async (idToken: string) => {
    const p = await auth.signInFirebase(idToken)
    after(p.onboarded)
  }

  if (auth.status === 'in' && auth.profile && !demoBusy) return <Navigate to={auth.profile.onboarded ? '/dashboard' : '/onboarding/about'} replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const p = mode === 'signup' ? await auth.signUp(email, password, '') : await auth.signIn(email, password)
      after(p.onboarded)
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-surface-container-lowest">
      <header className="fixed top-0 z-50 w-full bg-surface-container-lowest/90 shadow-[0_1px_8px_rgba(0,0,0,0.04)] backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1200px] items-center justify-between px-gutter-mobile md:px-gutter">
          <Logo />
          <nav className="flex items-center gap-1 font-label-md text-label-md text-on-surface-variant">
            <a href="/docs" target="_blank" rel="noreferrer" className="rounded-full px-3 py-1.5 hover:bg-surface-container-low hover:text-on-surface">API</a>
            <a href="https://github.com/shreytiwari09/TailorTex" target="_blank" rel="noreferrer" className="rounded-full px-3 py-1.5 hover:bg-surface-container-low hover:text-on-surface">GitHub</a>
          </nav>
        </div>
      </header>

      <main className="pt-16">
        <div className="relative overflow-hidden">
          <div className="pointer-events-none absolute left-1/2 top-0 -z-10 h-[480px] w-[780px] -translate-x-1/2 rounded-full bg-gradient-to-b from-primary-fixed/25 to-transparent blur-3xl" />
          <section className="mx-auto flex max-w-[1200px] flex-col items-center px-gutter-mobile pb-space-xl pt-space-2xl text-center md:px-gutter">
            <Badge tone="neutral" className="mb-6 gap-2 px-3 py-1 text-primary-container shadow-sm">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary-container" />
              Your template stays intact · Nothing gets invented
            </Badge>
            <h1 className="max-w-[880px] font-display-hero-mobile text-display-hero-mobile tracking-tight text-on-surface md:font-display-hero md:text-display-hero">
              Tailor your LaTeX resume to every job.
            </h1>
            <p className="mt-space-md max-w-[660px] font-body-lg text-body-lg leading-relaxed text-on-surface-variant">
              Paste a job description and get your own template back with the right keywords in the right places. It always compiles, and every change is backed by your real background.
            </p>

            <div className="mt-space-xl flex w-full max-w-[440px] flex-col items-center gap-space-md rounded-xl bg-surface-container-lowest p-space-lg shadow-xl">
              {!auth.accounts && auth.status !== 'loading' && (
                <Notice tone="warn" className="w-full text-left">Accounts aren't switched on for this server. You can still try the demo.</Notice>
              )}
              {auth.accounts && auth.firebase && (
                <Suspense fallback={<Skeleton className="h-56 w-full" />}>
                  <FirebaseSignIn config={auth.firebase} onIdToken={firebaseIn} />
                </Suspense>
              )}
              {auth.accounts && !auth.firebase && (
                <>
                  {auth.googleClientId && (
                    <>
                      <GoogleButton clientId={auth.googleClientId} onCredential={google} onError={setError} />
                      <div className="flex w-full items-center gap-3">
                        <div className="h-px flex-1 bg-surface-variant" />
                        <span className="font-label-sm text-label-sm uppercase tracking-wider text-secondary">or</span>
                        <div className="h-px flex-1 bg-surface-variant" />
                      </div>
                    </>
                  )}
                  <form onSubmit={submit} className="flex w-full flex-col gap-2.5" aria-label={mode === 'signup' ? 'Create account' : 'Sign in'}>
                    <label className="flex items-center gap-2 rounded-full bg-surface-container-low px-4 py-1 shadow-sm focus-within:ring-4 focus-within:ring-primary-container/15">
                      <Icon name="mail" className="text-[18px] text-secondary" />
                      <input
                        type="email"
                        required
                        autoComplete="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="Your email"
                        aria-label="Email"
                        className="w-full bg-transparent py-2.5 font-body-md text-body-md text-on-surface placeholder:text-secondary focus:outline-none"
                      />
                    </label>
                    <label className="flex items-center gap-2 rounded-full bg-surface-container-low px-4 py-1 shadow-sm focus-within:ring-4 focus-within:ring-primary-container/15">
                      <Icon name="lock" className="text-[18px] text-secondary" />
                      <input
                        type="password"
                        required
                        minLength={mode === 'signup' ? 8 : undefined}
                        autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder={mode === 'signup' ? 'Choose a password (8+ characters)' : 'Your password'}
                        aria-label="Password"
                        className="w-full bg-transparent py-2.5 font-body-md text-body-md text-on-surface placeholder:text-secondary focus:outline-none"
                      />
                    </label>
                    {error && <Notice tone="bad" className="text-left">{error}</Notice>}
                    <Button type="submit" size="lg" loading={busy} className="w-full">
                      {mode === 'signup' ? 'Create free account' : 'Sign in'}
                    </Button>
                    <button
                      type="button"
                      onClick={() => {
                        setMode(mode === 'signup' ? 'signin' : 'signup')
                        setError(null)
                      }}
                      className="font-label-sm text-label-sm text-secondary hover:text-primary-container"
                    >
                      {mode === 'signup' ? 'Already have an account? Sign in' : 'New here? Create an account'}
                    </button>
                  </form>
                </>
              )}
              <span className="inline-flex items-center gap-1.5">
                {auth.accounts ? (
                  <button type="button" disabled={demoBusy} onClick={demo} className="py-1 font-label-sm text-label-sm text-secondary transition-colors hover:text-primary-container disabled:opacity-60">
                    {demoBusy ? 'Opening the demo…' : 'Try the demo with a sample resume'}
                  </button>
                ) : (
                  <a href="/demo.html?sample" className="py-1 font-label-sm text-label-sm text-secondary transition-colors hover:text-primary-container">
                    Try the demo with a sample resume
                  </a>
                )}
                <InfoTip>Opens a temporary workspace with a sample resume and background, so you can try the whole product. You bring your own model key. It is deleted after two days.</InfoTip>
              </span>
            </div>

            <div className="mt-space-lg flex flex-wrap items-center justify-center gap-x-space-lg gap-y-2 font-label-sm text-label-sm text-on-surface-variant">
              {['Template untouched', 'Always compiles', 'Nothing invented'].map((t) => (
                <div key={t} className="flex items-center gap-1.5">
                  <Icon name="check_circle" fill className="text-[16px] text-primary-container" />
                  <span className="font-medium">{t}</span>
                </div>
              ))}
            </div>
          </section>

          <Example />
        </div>

        <section className="mx-auto max-w-[1200px] px-gutter-mobile py-space-2xl md:px-gutter">
          <div className="mx-auto mb-space-xl max-w-[640px] text-center">
            <span className="font-label-sm text-label-sm font-semibold uppercase tracking-widest text-primary-container">How it stays honest</span>
            <h2 className="mt-2 font-headline-lg-mobile text-headline-lg-mobile tracking-tight text-on-surface md:font-headline-lg md:text-headline-lg">
              Built for people who won't send made-up claims.
            </h2>
          </div>
          <div className="grid grid-cols-1 gap-gutter md:grid-cols-3">
            <Feature icon="hub" title="Matched to the job" text="Reads the posting's must-haves and nice-to-haves, checks them against your resume and background, and shows what's missing and why.">
              <Meter label="Must-have keywords" value="63% → 87%" width="87%" />
            </Feature>
            <Feature icon="verified_user" title="Nothing invented" text="Every new skill, tool and number is checked in code against your resume and your own context. Anything unsupported is refused, and you see it.">
              <div className="rounded-lg bg-surface-container-low p-3 font-code-sm text-code-sm text-on-surface-variant">
                <span className="text-error">blocked</span> · “Terraform” isn't in your background
              </div>
            </Feature>
            <Feature icon="description" title="Your template, edited in place" text="Only bullets, the summary and skills lines change. Download the .tex and PDF, or open it in Overleaf.">
              <div className="rounded-lg bg-surface-container-low p-3 font-code-sm text-code-sm text-on-surface-variant">
                Education · <span className="text-primary-container">kept as is</span>
              </div>
            </Feature>
          </div>
        </section>
      </main>

      <footer className="border-t border-outline-variant/40">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-2 px-gutter-mobile py-6 font-code-sm text-code-sm text-outline md:px-gutter">
          <span>TailorTeX · built for HackDevengers 2.0</span>
          <span>Your resume and details go only to the model provider you choose.</span>
        </div>
      </footer>
    </div>
  )
}

function Feature({ icon, title, text, children }: { icon: string; title: string; text: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col rounded-xl border border-outline-variant/50 bg-surface-container-lowest p-space-xl shadow-sm transition-all hover:shadow-md">
      <div className="mb-space-lg flex h-10 w-10 items-center justify-center rounded-lg bg-surface-container text-primary-container">
        <Icon name={icon} className="text-[22px]" />
      </div>
      <h3 className="mb-2 font-headline-sm text-headline-sm text-on-surface">{title}</h3>
      <p className="font-body-md text-body-md leading-relaxed text-on-surface-variant">{text}</p>
      <div className="mt-space-lg">{children}</div>
    </div>
  )
}

function Meter({ label, value, width }: { label: string; value: string; width: string }) {
  return (
    <div className="rounded-lg bg-surface-container-low p-3">
      <div className="mb-1 flex items-center justify-between font-label-sm text-label-sm font-medium text-on-surface">
        <span>{label} <span className="font-normal text-outline">(example)</span></span>
        <span className="font-code-sm text-primary-container">{value}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-variant">
        <div className="h-full rounded-full bg-primary-container" style={{ width }} />
      </div>
    </div>
  )
}

/** A small, honest illustration of what a result looks like. */
function Example() {
  return (
    <section className="mx-auto max-w-[1200px] px-gutter-mobile pb-space-2xl md:px-gutter" aria-label="Example result">
      <div className="rounded-xl bg-surface-container-lowest p-2 shadow-xl sm:p-4">
        <div className="mb-3 flex items-center justify-between rounded-lg bg-surface-container-low px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="h-3 w-3 rounded-full bg-error/60" />
            <span className="h-3 w-3 rounded-full bg-primary-fixed" />
            <span className="h-3 w-3 rounded-full bg-primary-container/60" />
            <span className="mx-2 h-4 w-px bg-surface-variant" />
            <span className="font-code-sm text-code-sm text-secondary">Example · Backend Engineer at a payments company</span>
          </div>
          <Badge tone="accent" className="hidden sm:inline-flex">Must-have 63% → 87%</Badge>
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
          <div className="overflow-hidden rounded-lg bg-surface-container-low lg:col-span-7">
            <div className="flex items-center justify-between bg-surface-container px-4 py-2.5">
              <span className="flex items-center gap-1.5 font-label-sm text-label-sm font-semibold text-on-surface">
                <Icon name="difference" className="text-[16px] text-primary-container" /> Changes you review
              </span>
              <span className="font-code-sm text-code-sm text-tertiary">Rewritten · Experience</span>
            </div>
            <div className="space-y-3 p-4">
              <p className="rounded-lg bg-surface-container-lowest p-3 font-body-md text-body-md leading-7 text-on-surface">
                <span className="rounded bg-error-container px-1 text-on-error-container line-through">Built endpoints in Python</span>{' '}
                <span className="rounded bg-emerald-100 px-1 text-emerald-900">Built REST APIs in Python and Flask</span> for merchant onboarding, used by 1,200 merchants.
              </p>
              <div className="flex flex-wrap items-center justify-between gap-2 font-code-sm text-code-sm text-on-surface-variant">
                <span className="rounded bg-primary-fixed/50 px-2 py-0.5 text-primary">from your resume</span>
                <span className="flex gap-1.5">
                  <span className="rounded-full border border-outline-variant px-3 py-1">Keep</span>
                  <span className="rounded-full border border-outline-variant px-3 py-1">Revert</span>
                  <span className="rounded-full border border-outline-variant px-3 py-1">Edit</span>
                </span>
              </div>
            </div>
          </div>
          <div className="overflow-hidden rounded-lg bg-surface-container-low lg:col-span-5">
            <div className="flex items-center justify-between bg-surface-container px-4 py-2.5">
              <span className="flex items-center gap-1.5 font-label-sm text-label-sm font-semibold text-on-surface">
                <Icon name="verified_user" className="text-[16px] text-primary-container" /> Guardrails
              </span>
              <Badge tone="accent">Checked in code</Badge>
            </div>
            <ul className="space-y-2 p-4 font-body-sm text-body-sm">
              <li className="flex items-start gap-2 rounded-lg bg-surface-container-lowest p-3">
                <Icon name="check_circle" fill className="mt-0.5 text-[18px] text-emerald-600" />
                <span>Kubernetes added, backed by your GitHub project <span className="font-code-sm">ledgerly</span></span>
              </li>
              <li className="flex items-start gap-2 rounded-lg bg-surface-container-lowest p-3">
                <Icon name="block" className="mt-0.5 text-[18px] text-error" />
                <span>Terraform refused: nothing in your background shows it</span>
              </li>
              <li className="flex items-start gap-2 rounded-lg bg-surface-container-lowest p-3">
                <Icon name="lock" className="mt-0.5 text-[18px] text-outline" />
                <span>Education kept exactly as written</span>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </section>
  )
}
