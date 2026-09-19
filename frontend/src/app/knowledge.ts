import { useCallback, useEffect, useState } from 'react'
import { ApiError, type Evidence, type EvidenceSource } from '../api'
import { acct } from './client'
import { noteLines, toBase64 } from './format'

/** The person's knowledge base: entries, notes and confirmed skills, with the actions that change them. */
export function useKnowledge() {
  const [entries, setEntries] = useState<Evidence[]>([])
  const [notes, setNotes] = useState('')
  const [skills, setSkills] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const c = await acct.context()
      setEntries(c.entries)
      setNotes(c.notes)
      setSkills(c.skills)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load your context.')
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh()
  }, [refresh])

  const run = useCallback(async (label: string, work: () => Promise<string | void>) => {
    setBusy(label)
    setError(null)
    setMessage(null)
    try {
      const done = await work()
      if (done) setMessage(done)
      return true
    } catch (e) {
      setError(e instanceof ApiError || e instanceof Error ? e.message : 'Something went wrong.')
      return false
    } finally {
      setBusy(null)
    }
  }, [])

  const addLink = (kind: 'github' | 'portfolio', link: string) =>
    run(kind === 'github' ? 'Reading your GitHub…' : 'Reading your portfolio…', async () => {
      const r = await acct.addLinks({ [kind]: link })
      setEntries(r.entries)
      const res = r.results[0]
      if (res?.error) throw new Error(res.error)
      return `Added ${res?.added ?? 0} ${res?.added === 1 ? 'entry' : 'entries'}. ${r.notes.join(' ')}`.trim()
    })

  const addLinkedIn = (file: File) => {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Upload the PDF from LinkedIn: on your profile, More → Save to PDF.')
      return Promise.resolve(false)
    }
    if (file.size > 5_000_000) {
      setError('That PDF is larger than 5 MB.')
      return Promise.resolve(false)
    }
    return run('Reading your LinkedIn PDF…', async () => {
      const r = await acct.addLinkedIn({ pdf_base64: await toBase64(file) })
      setEntries(r.entries)
      return `Added ${r.added} ${r.added === 1 ? 'entry' : 'entries'} from LinkedIn. ${r.notes.join(' ')}`.trim()
    })
  }

  const saveNotes = (next: string, done?: string) =>
    run('Saving…', async () => {
      const r = await acct.saveNotes(next)
      setEntries(r.entries)
      setNotes(r.notes)
      return done
    })

  const addNotes = (text: string) => {
    const existing = noteLines(notes)
    const fresh = noteLines(text).filter((l) => !existing.includes(l))
    if (!fresh.length) {
      setMessage('Those are already saved.')
      return Promise.resolve(true)
    }
    return saveNotes([...existing, ...fresh].join('\n'), `Saved ${fresh.length} ${fresh.length === 1 ? 'note' : 'notes'}. They're indexed and ready to use.`)
  }

  const editEntry = (entry: Evidence, c: { title?: string; text?: string; skills?: string[] }) => {
    if (/^n\d+$/.test(entry.id)) {
      // Notes live in one text; change that line and save it again.
      const lines = noteLines(notes)
      const i = Number(entry.id.slice(1)) - 1
      if (c.text !== undefined && lines[i] !== undefined) lines[i] = c.text.replace(/\n+/g, ' ').trim()
      return saveNotes(lines.filter(Boolean).join('\n'), 'Note updated.')
    }
    return run('Saving…', async () => {
      const updated = await acct.editEntry(entry.id, c)
      setEntries((list) => list.map((e) => (e.id === entry.id ? updated : e)))
      return 'Entry updated and re-indexed.'
    })
  }

  const removeEntry = (entry: Evidence) =>
    run('Removing…', async () => {
      await acct.deleteEntry(entry.id)
      await refresh()
    })

  const saveSkills = (next: string[]) =>
    run('Saving…', async () => {
      setSkills((await acct.saveSkills(next)).skills)
    })

  return { entries, notes, skills, loading, busy, error, message, setError, setMessage, refresh, addLink, addLinkedIn, addNotes, editEntry, removeEntry, saveSkills }
}
export type Knowledge = ReturnType<typeof useKnowledge>


export type FilterKey = 'all' | 'github' | 'portfolio' | 'linkedin' | 'notes'
export const sourceOf = (e: Evidence): FilterKey => (e.source === 'fact' || e.source === 'skill' ? 'notes' : (e.source as EvidenceSource as FilterKey))
