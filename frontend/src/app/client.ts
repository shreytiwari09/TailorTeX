// Calls for the signed-in product. Same origin, so the session cookie goes along automatically.
import { ApiError, type Evidence, type Outline, type Result } from '../api'

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError("Can't reach the TailorTeX server. Is the backend running?", 0)
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') detail = data.detail
      else if (Array.isArray(data.detail)) detail = data.detail.map((d: { msg?: string }) => d.msg).join('; ')
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail, res.status)
  }
  return res.json() as Promise<T>
}

export type Links = { linkedin?: string; github?: string; portfolio?: string; other?: string }
export type Profile = {
  id: string
  account: { email: string | null; google: boolean; password: boolean; avatar_url: string | null; demo: boolean }
  details: { full_name: string; headline: string; location: string; phone: string; public_email: string; links: Links }
  resume_tex: string
  notes: string
  skills: string[]
  model: { provider: string | null; model: string | null; key_saved: boolean; key_hint: string | null }
  context_counts: Record<string, number>
  onboarded: boolean
  updated_at: string | null
}
export type AuthState = { signed_in: boolean; accounts: boolean; profile?: Profile | null }
export type RunSummary = {
  id: string
  created_at: string
  job_title: string
  company: string | null
  must_before: number | null
  must_after: number | null
  health: number | null
  model: string | null
  has_pdf: boolean
  filename: string | null
}
export type SavedRun = Result & { saved_run_id: string; jd: string }
export type LinkImport = { source: string; link: string; added: number; error: string | null }
export type ModelList = { model: Profile['model']; models: { id: string; label: string }[]; recommended: string | null }

export const acct = {
  config: () => req<{ accounts: boolean; google_client_id: string | null }>('GET', '/api/auth/config'),
  me: () => req<AuthState>('GET', '/api/auth/me'),
  signUp: (email: string, password: string, full_name: string) => req<{ created: boolean; profile: Profile }>('POST', '/api/auth/signup', { email, password, full_name }),
  signIn: (email: string, password: string) => req<{ created: boolean; profile: Profile }>('POST', '/api/auth/signin', { email, password }),
  google: (credential: string) => req<{ created: boolean; profile: Profile }>('POST', '/api/auth/google', { credential }),
  demo: () => req<{ created: boolean; profile: Profile; jd: string }>('POST', '/api/auth/demo'),
  signOut: () => req<{ ok: boolean }>('POST', '/api/auth/signout'),

  profile: () => req<Profile>('GET', '/api/profile'),
  saveDetails: (d: Partial<Profile['details']> & { onboarded?: boolean }) => req<Profile>('PUT', '/api/profile', d),
  saveResume: (tex: string) => req<{ outline: Outline | null }>('PUT', '/api/profile/resume', { tex }),
  saveModel: (m: { provider?: string | null; model?: string | null; key?: string | null }) => req<ModelList>('PUT', '/api/profile/model', m),
  removeModel: () => req<{ model: Profile['model'] }>('DELETE', '/api/profile/model'),
  deleteAccount: () => req<{ deleted: boolean }>('DELETE', '/api/profile'),

  context: () => req<{ entries: Evidence[]; notes: string; skills: string[] }>('GET', '/api/profile/context'),
  addLinks: (b: { github?: string; portfolio?: string }) => req<{ results: LinkImport[]; notes: string[]; entries: Evidence[] }>('POST', '/api/profile/context/links', b),
  addLinkedIn: (b: { pdf_base64?: string; text?: string }) => req<{ added: number; notes: string[]; entries: Evidence[] }>('POST', '/api/profile/context/linkedin', b),
  saveNotes: (notes: string) => req<{ entries: Evidence[]; notes: string }>('PUT', '/api/profile/notes', { notes }),
  saveSkills: (skills: string[]) => req<{ skills: string[] }>('PUT', '/api/profile/skills', { skills }),
  editEntry: (id: string, c: { title?: string; text?: string; skills?: string[] }) => req<Evidence>('PATCH', `/api/profile/context/${encodeURIComponent(id)}`, c),
  deleteEntry: (id: string) => req<{ deleted: boolean }>('DELETE', `/api/profile/context/${encodeURIComponent(id)}`),

  runs: () => req<{ runs: RunSummary[] }>('GET', '/api/runs'),
  run: (id: string) => req<SavedRun>('GET', `/api/runs/${id}`),
  rebuildRun: (id: string, ops: unknown[], compile = true) => req<{ tex: string; pdf: string | null; after: Result['after']; warnings: string[] }>('POST', `/api/runs/${id}/rebuild`, { ops, compile }),
  deleteRun: (id: string) => req<{ deleted: boolean }>('DELETE', `/api/runs/${id}`),
}
