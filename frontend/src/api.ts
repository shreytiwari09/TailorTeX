// Types and calls for the TailorTeX backend. Everything goes to the app's own origin.

export type Provider = { id: string; label: string; key_url: string; free_tier: boolean }
export type Config = {
  server_key: boolean
  server_provider: string | null
  server_model: string | null
  tex: boolean
  providers: Provider[]
}
export type ModelInfo = { id: string; label: string; price_in: number | null; price_out: number | null }
export type EvidenceSource = 'github' | 'skill' | 'fact' | 'portfolio' | 'linkedin'
export type Evidence = { id: string; source: EvidenceSource; title: string; text: string; skills: string[]; url?: string | null }

export type LintIssue = { id: string; severity: 'warn' | 'info'; message: string; fixable: boolean }
export type OutlineBlock = { id: string; kind: string; text: string; label: string | null; locked: boolean; lock_reason: string | null }
export type Outline = {
  profile: string
  name: string
  engine: string
  bullet_budget: number
  sections: { id: string; title: string; kind: string; locked: boolean; blocks: OutlineBlock[]; entries: { id: string; heading: string; bullets: OutlineBlock[] }[] }[]
  stats: { sections: number; bullets: number; editable: number }
  lint: LintIssue[]
}

export type Check = { id: string; label: string; ok: boolean; detail: string; weight: number; score?: number | null }
export type Finding = { check: string; block_id: string; text: string; hint: string }
export type Metrics = {
  must_have: number
  nice_to_have: number
  title: number
  health: number | null
  checks: Check[]
  pages: number | null
  page_fill: number | null
  // Older saved runs were made before these existed, so every read goes through format.ts.
  quality?: number
  quality_checks?: Check[]
  quality_findings?: Finding[]
}
export type TermStatus = 'context' | 'listed' | 'missing'
export type Gap = { term: string; weight: number; must: boolean; status: 'present' | 'evidence' | 'missing'; evidence_ids: string[] }
export type Keyword = {
  term: string
  weight: number
  must: boolean
  before: TermStatus
  after: TermStatus
  in_pdf: boolean | null
  gap: Gap['status'] | null
  evidence_ids: string[]
}
export type OpKind = 'rewrite' | 'add' | 'drop' | 'reorder' | 'reorder_entries' | 'drop_entry'
export type Op = {
  op: OpKind
  target: string
  text: string | null
  after: string | null
  order: string[] | null
  evidence: string[]
  reason: string
  source: 'model' | 'fit' | 'user'
}
export type Change = {
  id: number
  op: OpKind
  target: string
  reason: string
  evidence: string[]
  source: Op['source']
  section: string
  heading: string
  before: string
  after: string
  before_list: string[] | null
  after_list: string[] | null
  terms?: string[]
  gain?: number
}
export type Blocked = { attempt: number; arm: string; op: string; rule: string; message: string; text: string | null; retried: boolean }
export type JobTerm = { term: string; weight: number }
export type Analysis = {
  title: string
  company: string | null
  seniority: string | null
  role_family: string | null
  must_have: JobTerm[]
  nice_to_have: JobTerm[]
  summary: string | null
}
export type Result = {
  type: 'result'
  run_id: string
  arm: string
  context: string
  candidates: { arm: string; reward: number; must_have: number; applied: number; blocked: number }[]
  reward: number
  reward_parts: Record<string, number>
  analysis: Analysis
  gaps: Gap[]
  before: Metrics
  after: Metrics
  keywords: Keyword[]
  changes: Change[]
  ops: Op[]
  blocked: Blocked[]
  left_out: { term: string; must: boolean; weight: number }[]
  suggestions: Suggestion[]
  recommendations?: Recommendation[]
  ats?: { before: number; after: number }
  gains?: { gaps: GapGain[]; quality: number }
  fit_note: string | null
  tex: string
  pdf: string | null
  page_limit: number
  filename: string
  engine: string
  usage: { provider: string; model: string; input_tokens: number; output_tokens: number; calls: number }
  warnings: string[]
}
export type GapGain = { term: string; must: boolean; weight: number; gain: number; from: TermStatus }
export type Recommendation = {
  priority: 'high' | 'medium' | 'low'
  group: string
  title: string
  detail: string
  action: 'none' | 'fix_source' | 'confirm_skill' | 'use_context' | 'improve_writing'
  term: string | null
  evidence: string[]
}
export type Suggestion = {
  id: string
  title: string
  source: EvidenceSource
  url: string | null
  added: string[]
  still_missing: string[]
  must: string[]
  cited: boolean
}
export type ProfileResult = { evidence: Evidence[]; skills: string[]; replaces: string[]; used_model: boolean; note: string | null }
export type LinkResult = {
  link: string
  kind: 'github_user' | 'github_repo' | 'linkedin' | 'portfolio' | 'invalid'
  evidence: Evidence[]
  note: string | null
  error: string | null
  url: string | null
}
export type ProfileRequest = { kind: 'linkedin' | 'linkedin_posts' | 'portfolio'; pdf_base64?: string; zip_base64?: string; text?: string; url?: string }
export type ProgressEvent = {
  type: 'progress'
  stage: string
  status: 'start' | 'done' | 'warn' | 'info'
  message: string
  data: Record<string, unknown>
}
export type StreamEvent =
  | ProgressEvent
  | Result
  | { type: 'start'; provider: string; model: string }
  | { type: 'error'; kind: string; message: string }

export type RebuildResult = { tex: string; pdf: string | null; after: Metrics; applied: Op[]; warnings: string[] }

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, body?: unknown): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, body === undefined ? undefined : {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
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

export const api = {
  config: () => request<Config>('/api/config'),
  models: (key: string, provider: string | null) =>
    request<{ provider: string; models: ModelInfo[]; recommended: string | null }>('/api/models', { key: key || null, provider }),
  sample: () => request<{ tex: string; jd: string; evidence: Evidence[]; skills: string[]; notes: string }>('/api/sample'),
  template: () => request<{ tex: string }>('/api/template'),
  parse: (tex: string) => request<Outline>('/api/parse', { tex }),
  lintFix: (tex: string, fix: string) => request<{ tex: string; outline: Outline }>('/api/lint/fix', { tex, fix }),
  githubRepos: (username: string) =>
    request<{ repos: { name: string; description: string; language: string | null; topics: string[]; stars: number; fork: boolean; url: string }[] }>(
      '/api/evidence/github',
      { username },
    ),
  githubImport: (username: string, repos: string[]) => request<{ evidence: Evidence[] }>('/api/evidence/github', { username, repos }),
  profile: (body: ProfileRequest & { key: string | null; provider: string | null; model: string | null }) =>
    request<ProfileResult>('/api/evidence/profile', body),
  links: (body: { links: string[]; key: string | null; provider: string | null; model: string | null }) =>
    request<{ results: LinkResult[]; notes: string[] }>('/api/evidence/links', body),
  rebuild: (body: unknown) => request<RebuildResult>('/api/rebuild', body),
  forget: (user: string) => request<{ deleted: boolean }>('/api/forget', { user }),
  feedback: (body: unknown) => request<{ reward: number; style_rules: string[] | null }>('/api/feedback', body),
}

/** POST to /api/tailor and read the server-sent events as they arrive. */
export async function streamTailor(body: unknown, onEvent: (e: StreamEvent) => void, signal: AbortSignal, url = '/api/tailor'): Promise<void> {
  let res: Response
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError("Can't reach the TailorTeX server. Is the backend running?", 0)
  }
  if (!res.ok || !res.body) {
    let detail = `Request failed (${res.status})`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') detail = data.detail
    } catch {
      /* not JSON */
    }
    throw new ApiError(detail, res.status)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const chunk = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const data = chunk
        .split('\n')
        .filter((l) => l.startsWith('data: '))
        .map((l) => l.slice(6))
        .join('\n')
      if (data) onEvent(JSON.parse(data) as StreamEvent)
    }
  }
}

/** Same rules as the backend: guess the provider from the key's shape. */
export function detectProvider(key: string): string | null {
  const k = key.trim()
  if (!k) return null
  if (k.startsWith('sk-ant-')) return 'anthropic'
  if (k.startsWith('sk-or-')) return 'openrouter'
  if (k.startsWith('gsk_')) return 'groq'
  if (k.startsWith('AIza')) return 'google'
  if (/^sk-(proj|svcacct|admin)-/.test(k)) return 'openai'
  if (/^sk-[a-f0-9]{32}$/.test(k)) return 'deepseek'
  if (k.startsWith('sk-')) return 'openai'
  if (/^[A-Za-z0-9]{32}$/.test(k)) return 'mistral'
  return null
}
