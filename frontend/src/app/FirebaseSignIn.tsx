import { getApp, getApps, initializeApp } from 'firebase/app'
import {
  GoogleAuthProvider,
  createUserWithEmailAndPassword,
  getAuth,
  inMemoryPersistence,
  sendEmailVerification,
  sendPasswordResetEmail,
  setPersistence,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  type Auth,
  type User,
} from 'firebase/auth'
import { useMemo, useState, type FormEvent } from 'react'
import { Button, Icon, Notice } from './ui'
import type { FirebaseConfig } from './client'

function firebaseAuth(config: FirebaseConfig): Auth {
  const app = getApps().length ? getApp() : initializeApp({ apiKey: config.apiKey, authDomain: config.authDomain, projectId: config.projectId, ...(config.appId ? { appId: config.appId } : {}) })
  return getAuth(app)
}

/** Firebase's error codes in words a person can act on. null means nothing to say (they closed the window). */
function friendly(e: unknown): string | null {
  const code = (e as { code?: string })?.code ?? ''
  const known: Record<string, string | null> = {
    'auth/email-already-in-use': 'An account with that email already exists. Sign in instead.',
    'auth/invalid-email': "That doesn't look like an email address.",
    'auth/weak-password': 'Use a password of at least 8 characters.',
    'auth/invalid-credential': 'Wrong email or password.',
    'auth/wrong-password': 'Wrong email or password.',
    'auth/user-not-found': 'Wrong email or password.',
    'auth/too-many-requests': 'Too many attempts. Wait a few minutes and try again.',
    'auth/network-request-failed': "Can't reach Google's sign-in service. Check your connection.",
    'auth/popup-closed-by-user': null,
    'auth/cancelled-popup-request': null,
    'auth/popup-blocked': 'Your browser blocked the sign-in window. Allow pop-ups for this site and try again.',
    'auth/unauthorized-domain': "This site's address isn't on Firebase's list of authorized domains (Authentication > Settings).",
    'auth/operation-not-allowed': "That sign-in method isn't switched on in Firebase (Authentication > Sign-in method).",
    'auth/invalid-api-key': "The Firebase settings on this server aren't right.",
    'auth/api-key-not-valid.-please-pass-a-valid-api-key.': "The Firebase settings on this server aren't right.",
  }
  if (code in known) return known[code]
  return e instanceof Error ? e.message.replace(/^Firebase: /, '') : 'Something went wrong.'
}

type Mode = 'signup' | 'signin' | 'reset'

/** Sign-in through Firebase Authentication. The browser signs in with Firebase, then trades its ID token for our own session. */
export default function FirebaseSignIn({ config, onIdToken }: { config: FirebaseConfig; onIdToken: (idToken: string) => Promise<void> }) {
  const auth = useMemo(() => firebaseAuth(config), [config])
  const ready = useMemo(() => setPersistence(auth, inMemoryPersistence).catch(() => undefined), [auth]) // nothing stays in the browser; our own session is the login
  const [mode, setMode] = useState<Mode>('signup')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [pending, setPending] = useState<User | null>(null) // signed up or in, but the address isn't verified yet

  const run = async (work: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    setInfo(null)
    try {
      await ready
      await work()
    } catch (e) {
      setError(friendly(e))
    } finally {
      setBusy(false)
    }
  }

  const finish = async (user: User, force = false) => {
    await onIdToken(await user.getIdToken(force))
    await signOut(auth).catch(() => undefined)
  }

  const google = () => run(async () => finish((await signInWithPopup(auth, new GoogleAuthProvider())).user))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      if (mode === 'reset') {
        await sendPasswordResetEmail(auth, email.trim()).catch((err: { code?: string }) => {
          if (err.code !== 'auth/user-not-found') throw err
        })
        setInfo('If an account exists for that email, a reset link is on its way.')
        return
      }
      if (mode === 'signup') {
        const { user } = await createUserWithEmailAndPassword(auth, email.trim(), password)
        await sendEmailVerification(user)
        setPending(user)
        return
      }
      const { user } = await signInWithEmailAndPassword(auth, email.trim(), password)
      if (user.emailVerified) await finish(user)
      else setPending(user)
    })
  }

  const verified = () =>
    run(async () => {
      if (!pending) return
      await pending.reload()
      if (!pending.emailVerified) {
        setError("That address isn't verified yet. Open the link in your email (check spam too), then try again.")
        return
      }
      await finish(pending, true)
    })

  const resend = () =>
    run(async () => {
      if (!pending) return
      await sendEmailVerification(pending)
      setInfo('Sent again.')
    })

  if (pending) {
    return (
      <div className="flex w-full flex-col gap-space-md text-center" role="status">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary-container/10"><Icon name="mark_email_unread" className="text-[26px] text-primary" /></div>
        <div>
          <h2 className="font-headline-sm text-headline-sm text-on-surface">Check your email</h2>
          <p className="mt-1 font-body-md text-body-md text-on-surface-variant">We sent a link to <span className="font-semibold text-on-surface">{pending.email}</span>. Open it to confirm the address, then come back here.</p>
        </div>
        {error && <Notice tone="bad" className="text-left">{error}</Notice>}
        {info && <Notice tone="good" className="text-left">{info}</Notice>}
        <Button size="lg" loading={busy} onClick={verified} className="w-full">I've verified my email</Button>
        <div className="flex items-center justify-center gap-4 font-label-sm text-label-sm text-secondary">
          <button type="button" onClick={resend} disabled={busy} className="hover:text-primary-container disabled:opacity-60">Send it again</button>
          <button type="button" onClick={() => { setPending(null); setError(null); setInfo(null); void signOut(auth).catch(() => undefined) }} className="hover:text-primary-container">Use a different email</button>
        </div>
      </div>
    )
  }

  const label = mode === 'signup' ? 'Create account' : mode === 'signin' ? 'Sign in' : 'Reset password'
  return (
    <div className="flex w-full flex-col items-center gap-space-md">
      <button
        type="button"
        onClick={google}
        disabled={busy}
        className="flex min-h-[44px] w-full items-center justify-center gap-3 rounded-full border border-outline-variant bg-surface-container-lowest px-4 py-2.5 font-label-md text-label-md font-semibold text-on-surface shadow-sm transition-colors hover:bg-surface-container-low disabled:opacity-60"
      >
        <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
          <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.5l6.7-6.7C35.7 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.8 6.1C12.3 13.6 17.7 9.5 24 9.5z" />
          <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z" />
          <path fill="#FBBC05" d="M10.4 28.7A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.2.9-4.7l-7.8-6.1A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.8l7.8-6.1z" />
          <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.8 2.3-8.4 2.3-6.3 0-11.7-4.1-13.6-9.8l-7.8 6.1C6.5 42.6 14.6 48 24 48z" />
        </svg>
        Continue with Google
      </button>
      <div className="flex w-full items-center gap-3">
        <div className="h-px flex-1 bg-surface-variant" />
        <span className="font-label-sm text-label-sm uppercase tracking-wider text-secondary">or</span>
        <div className="h-px flex-1 bg-surface-variant" />
      </div>
      <form onSubmit={submit} className="flex w-full flex-col gap-2.5" aria-label={label}>
        <label className="flex items-center gap-2 rounded-full bg-surface-container-low px-4 py-1 shadow-sm focus-within:ring-4 focus-within:ring-primary-container/15">
          <Icon name="mail" className="text-[18px] text-secondary" />
          <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Your email" aria-label="Email" className="w-full bg-transparent py-2.5 font-body-md text-body-md text-on-surface placeholder:text-secondary focus:outline-none" />
        </label>
        {mode !== 'reset' && (
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
        )}
        {error && <Notice tone="bad" className="text-left">{error}</Notice>}
        {info && <Notice tone="good" className="text-left">{info}</Notice>}
        <Button type="submit" size="lg" loading={busy} className="w-full">{mode === 'signup' ? 'Create free account' : label}</Button>
        <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 font-label-sm text-label-sm text-secondary">
          <button type="button" onClick={() => { setMode(mode === 'signup' ? 'signin' : 'signup'); setError(null); setInfo(null) }} className="hover:text-primary-container">
            {mode === 'signup' ? 'Already have an account? Sign in' : mode === 'signin' ? 'New here? Create an account' : 'Back to sign in'}
          </button>
          {mode === 'signin' && <button type="button" onClick={() => { setMode('reset'); setError(null); setInfo(null) }} className="hover:text-primary-container">Forgot your password?</button>}
        </div>
      </form>
    </div>
  )
}
