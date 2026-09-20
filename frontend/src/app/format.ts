export const pct = (x: number | null | undefined) => (x === null || x === undefined ? '–' : `${Math.round(x * 100)}%`)

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return ''
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  if (s < 86400 * 2) return 'yesterday'
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export async function toBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let bin = ''
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(bin)
}

/** One entry per blank-line-separated block, the same split the server makes for notes. */
export function noteBlocks(notes: string): string[] {
  return notes
    .split(/\n\s*\n+/)
    .map((block) =>
      block
        .split('\n')
        .map((l) => l.replace(/^\s*(?:[-*\u2022\u00b7]|\d+[.)])\s*/, '').trim())
        .filter(Boolean)
        .join('\n'),
    )
    .filter(Boolean)
}

/** A short name for an entry: its first sentence or line, shortened. */
export function blockTitle(text: string): string {
  const first = text.trim().split('\n')[0] ?? ''
  const sentence = first.split(/(?<=[.!?])\s/)[0]?.trim() || first
  const head = sentence.length <= 60 ? sentence : first
  return head.length <= 60 ? head : head.slice(0, 58).trimEnd() + '\u2026'
}
