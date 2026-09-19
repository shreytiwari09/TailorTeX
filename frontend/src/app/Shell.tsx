import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from './auth'
import { Avatar, Icon, LinkButton, Logo } from './ui'

const NAV = [
  { to: '/dashboard', label: 'Resumes' },
  { to: '/context', label: 'My context' },
]

/** Top bar and page frame for signed-in pages. */
export function Shell() {
  const { profile, signOut } = useAuth()
  const navigate = useNavigate()
  const [menu, setMenu] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!menu) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setMenu(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [menu])

  const name = profile?.details.full_name || profile?.account.email || 'You'
  return (
    <div className="flex min-h-screen flex-col bg-surface-container-lowest">
      <header className="fixed top-0 z-50 w-full bg-surface-container-lowest/90 shadow-[0_1px_8px_rgba(0,0,0,0.04)] backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1200px] items-center justify-between px-gutter-mobile md:px-gutter">
          <div className="flex items-center gap-space-lg md:gap-space-xl">
            <Link to="/dashboard" aria-label="TailorTeX home" className="transition-opacity hover:opacity-80">
              <Logo />
            </Link>
            <nav className="flex items-center gap-1" aria-label="Main">
              {NAV.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  className={({ isActive }) =>
                    `whitespace-nowrap rounded-full px-3 py-1.5 font-label-md text-label-md transition-all ${isActive ? 'bg-surface-container font-semibold text-on-surface' : 'text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'}`
                  }
                >
                  {n.label}
                </NavLink>
              ))}
              <a href="/docs" target="_blank" rel="noreferrer" className="hidden whitespace-nowrap rounded-full px-3 py-1.5 font-label-md text-label-md text-on-surface-variant transition-all hover:bg-surface-container-low hover:text-on-surface sm:block">
                API
              </a>
            </nav>
          </div>
          <div className="flex items-center gap-space-md">
            <div className="hidden sm:block">
              <LinkButton to="/new" size="sm">
                <Icon name="add" className="text-[16px]" /> New tailoring
              </LinkButton>
            </div>
            <Link to="/new" aria-label="New tailoring" className="flex h-9 w-9 items-center justify-center rounded-full bg-primary-container text-on-primary-container shadow-sm sm:hidden">
              <Icon name="add" className="text-[20px]" />
            </Link>
            <div ref={ref} className="relative">
              <button type="button" aria-label="Account menu" aria-expanded={menu} onClick={() => setMenu((m) => !m)} className="flex items-center rounded-full ring-offset-2 focus-visible:outline-2 focus-visible:outline-primary-container">
                <Avatar name={name} url={profile?.account.avatar_url} />
              </button>
              {menu && (
                <div className="absolute right-0 top-full mt-2 w-60 overflow-hidden rounded-xl border border-outline-variant/60 bg-surface-container-lowest shadow-xl">
                  <div className="border-b border-outline-variant/50 px-4 py-3">
                    <div className="truncate font-label-md text-label-md font-semibold text-on-surface">{name}</div>
                    <div className="truncate font-body-sm text-body-sm text-on-surface-variant">{profile?.account.demo ? 'Demo workspace' : profile?.account.email}</div>
                  </div>
                  <div className="p-1.5">
                    <MenuItem icon="tune" label="Settings" onClick={() => { setMenu(false); navigate('/settings') }} />
                    <MenuItem icon="logout" label="Sign out" onClick={async () => { setMenu(false); await signOut(); navigate('/') }} />
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1200px] flex-1 px-gutter-mobile pb-space-2xl pt-[88px] md:px-gutter">
        {profile?.account.demo && (
          <div className="mb-space-lg flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-lg bg-primary-container/10 px-4 py-2.5 font-body-sm text-body-sm text-on-surface">
            <span className="flex items-center gap-2"><Icon name="science" className="text-[18px] text-primary" /> Demo workspace with a sample resume and background. It is deleted after two days.</span>
            <button type="button" onClick={async () => { await signOut(); navigate('/') }} className="font-label-md text-label-md font-semibold text-primary hover:underline">Create a real account</button>
          </div>
        )}
        <Outlet />
      </main>
      <footer className="border-t border-outline-variant/40">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-2 px-gutter-mobile py-5 font-code-sm text-code-sm text-outline md:px-gutter">
          <span>TailorTeX · built for HackDevengers 2.0</span>
          <a href="https://github.com/shreytiwari09/TailorTex" target="_blank" rel="noreferrer" className="hover:text-on-surface">Source on GitHub</a>
        </div>
      </footer>
    </div>
  )
}

function MenuItem({ icon, label, onClick }: { icon: string; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left font-label-md text-label-md text-on-surface hover:bg-surface-container-low">
      <Icon name={icon} className="text-[18px] text-on-surface-variant" />
      {label}
    </button>
  )
}
