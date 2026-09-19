// Small helpers: word diff, browser storage, downloads.

export type DiffPart = { kind: 'same' | 'del' | 'ins'; text: string }

/** Word-level diff (longest common subsequence), keeping the original spacing. */
export function wordDiff(before: string, after: string): DiffPart[] {
  const a = before.split(/(\s+)/).filter((t) => t !== '')
  const b = after.split(/(\s+)/).filter((t) => t !== '')
  const n = a.length
  const m = b.length
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const out: DiffPart[] = []
  const push = (kind: DiffPart['kind'], text: string) => {
    const last = out[out.length - 1]
    if (last && last.kind === kind) last.text += text
    else out.push({ kind, text })
  }
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      push('same', a[i])
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push('del', a[i++])
    } else {
      push('ins', b[j++])
    }
  }
  while (i < n) push('del', a[i++])
  while (j < m) push('ins', b[j++])
  return out
}

/** Plain text with **bold** markers removed. */
export const plain = (s: string) => s.replace(/\*\*/g, '')

// Browser storage can be unavailable (private windows, blocked site data), so every access is guarded.
function makeStore(area: () => Storage) {
  return {
    get<T>(key: string, fallback: T): T {
      try {
        const raw = area().getItem(`tailortex:${key}`)
        return raw === null ? fallback : (JSON.parse(raw) as T)
      } catch {
        return fallback
      }
    },
    set(key: string, value: unknown) {
      try {
        area().setItem(`tailortex:${key}`, JSON.stringify(value))
      } catch {
        /* storage unavailable */
      }
    },
    remove(key: string) {
      try {
        area().removeItem(`tailortex:${key}`)
      } catch {
        /* storage unavailable */
      }
    },
  }
}

/** Kept on this device until cleared. */
export const store = makeStore(() => localStorage)
/** Kept for this browser tab, across reloads, until the tab is closed. */
export const session = makeStore(() => sessionStorage)

/** An anonymous ID for this browser, so the learning loop can personalize without an account. */
export function deviceId(): string {
  let id = store.get<string | null>('device', null)
  if (!id) {
    id = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : Math.random().toString(36).slice(2)
    store.set('device', id)
  }
  return id
}

export function downloadBlob(data: Blob, filename: string) {
  const url = URL.createObjectURL(data)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export function base64ToBlob(b64: string, type: string): Blob {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new Blob([bytes], { type })
}

/** Open the .tex in Overleaf through its public "open in Overleaf" endpoint. */
export function openInOverleaf(tex: string, name: string, engine: string) {
  const form = document.createElement('form')
  form.method = 'POST'
  form.action = 'https://www.overleaf.com/docs'
  form.target = '_blank'
  const fields: Record<string, string> = { encoded_snip: encodeURIComponent(tex), snip_name: name, engine }
  for (const [k, v] of Object.entries(fields)) {
    const input = document.createElement('input')
    input.type = 'hidden'
    input.name = k
    input.value = v
    form.appendChild(input)
  }
  document.body.appendChild(form)
  form.submit()
  form.remove()
}

export const pct = (x: number | null | undefined) => (x === null || x === undefined ? '–' : `${Math.round(x * 100)}%`)
