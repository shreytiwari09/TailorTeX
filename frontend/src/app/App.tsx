import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import { Shell } from './Shell'
import { Landing } from './pages/Landing'
import { Spinner } from './ui'

function Splash() {
  return (
    <div className="flex min-h-screen items-center justify-center text-primary-container">
      <Spinner className="h-6 w-6" />
    </div>
  )
}

/** Signed-in pages. Someone who hasn't finished setup is sent to onboarding first. */
function Protected({ onboarding = false }: { onboarding?: boolean }) {
  const { status, profile } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <Splash />
  if (status === 'out' || !profile) return <Navigate to="/" replace state={{ from: location.pathname }} />
  if (!onboarding && !profile.onboarded) return <Navigate to="/onboarding/about" replace />
  return <Outlet />
}

function Demo() {
  window.location.replace('/demo.html' + window.location.search)
  return <Splash />
}

function Placeholder({ name }: { name: string }) {
  return <div className="py-space-2xl font-headline-md text-headline-md text-on-surface">{name} — coming next</div>
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/demo" element={<Demo />} />
          <Route element={<Protected onboarding />}>
            <Route path="/onboarding/:step" element={<Placeholder name="Onboarding" />} />
          </Route>
          <Route element={<Protected />}>
            <Route element={<Shell />}>
              <Route path="/dashboard" element={<Placeholder name="Resumes" />} />
              <Route path="/new" element={<Placeholder name="New tailoring" />} />
              <Route path="/runs/:id" element={<Placeholder name="Result" />} />
              <Route path="/context" element={<Placeholder name="My context" />} />
              <Route path="/settings" element={<Placeholder name="Settings" />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
