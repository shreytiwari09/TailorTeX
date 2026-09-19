import { useEffect, useRef } from 'react'

type GoogleId = {
  initialize: (o: { client_id: string; callback: (r: { credential: string }) => void }) => void
  renderButton: (el: HTMLElement, o: Record<string, unknown>) => void
}
declare global {
  interface Window {
    google?: { accounts: { id: GoogleId } }
  }
}

let loading: Promise<void> | null = null
function loadScript(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve()
  loading ??= new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = 'https://accounts.google.com/gsi/client'
    s.async = true
    s.onload = () => resolve()
    s.onerror = () => {
      loading = null
      reject(new Error('Google sign-in could not load'))
    }
    document.head.appendChild(s)
  })
  return loading
}

/** Google's own "Continue with Google" button; shown only when the server has a Google client ID. */
export function GoogleButton({ clientId, onCredential, onError }: { clientId: string; onCredential: (c: string) => void; onError: (m: string) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let alive = true
    loadScript()
      .then(() => {
        if (!alive || !ref.current || !window.google) return
        window.google.accounts.id.initialize({ client_id: clientId, callback: (r) => onCredential(r.credential) })
        window.google.accounts.id.renderButton(ref.current, { type: 'standard', theme: 'outline', size: 'large', shape: 'pill', text: 'continue_with', width: 360 })
      })
      .catch((e: Error) => onError(e.message))
    return () => {
      alive = false
    }
  }, [clientId, onCredential, onError])
  return <div ref={ref} className="flex min-h-[44px] w-full justify-center" />
}
