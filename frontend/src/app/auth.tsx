import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { acct, type FirebaseConfig, type Profile } from './client'

type Status = 'loading' | 'out' | 'in'
type Auth = {
  status: Status
  accounts: boolean
  googleClientId: string | null
  firebase: FirebaseConfig | null
  profile: Profile | null
  setProfile: (p: Profile) => void
  signIn: (email: string, password: string) => Promise<Profile>
  signUp: (email: string, password: string, name: string) => Promise<Profile>
  signInGoogle: (credential: string) => Promise<Profile>
  signInFirebase: (idToken: string) => Promise<Profile>
  startDemo: () => Promise<{ profile: Profile; jd: string }>
  signOut: () => Promise<void>
}

const Ctx = createContext<Auth | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [accounts, setAccounts] = useState(true)
  const [googleClientId, setGoogle] = useState<string | null>(null)
  const [firebase, setFirebase] = useState<FirebaseConfig | null>(null)
  const [profile, setProfileState] = useState<Profile | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([acct.config().catch(() => null), acct.me().catch(() => null)]).then(([cfg, me]) => {
      if (cancelled) return
      setAccounts(cfg?.accounts ?? me?.accounts ?? false)
      setGoogle(cfg?.google_client_id ?? null)
      setFirebase(cfg?.firebase ?? null)
      if (me?.signed_in && me.profile) {
        setProfileState(me.profile)
        setStatus('in')
      } else setStatus('out')
    })
    return () => {
      cancelled = true
    }
  }, [])

  const setProfile = useCallback((p: Profile) => setProfileState(p), [])
  const done = useCallback((p: Profile) => {
    setProfileState(p)
    setStatus('in')
    return p
  }, [])

  const value = useMemo<Auth>(
    () => ({
      status,
      accounts,
      googleClientId,
      firebase,
      profile,
      setProfile,
      signIn: async (email, password) => done((await acct.signIn(email, password)).profile),
      signUp: async (email, password, name) => done((await acct.signUp(email, password, name)).profile),
      signInGoogle: async (credential) => done((await acct.google(credential)).profile),
      signInFirebase: async (idToken) => done((await acct.firebase(idToken)).profile),
      startDemo: async () => {
        const r = await acct.demo()
        return { profile: done(r.profile), jd: r.jd }
      },
      signOut: async () => {
        await acct.signOut().catch(() => undefined)
        setProfileState(null)
        setStatus('out')
      },
    }),
    [status, accounts, googleClientId, firebase, profile, setProfile, done],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

// oxlint-disable-next-line react/only-export-components
export function useAuth(): Auth {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth must be used inside AuthProvider')
  return v
}
