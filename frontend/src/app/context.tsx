import { useRef, useState } from 'react'
import type { Evidence } from '../api'
import { noteLines } from './format'
import { sourceOf, type FilterKey, type Knowledge } from './knowledge'
import { Badge, Button, Icon, Notice, TextArea, TextInput } from './ui'

// --- how each kind of entry looks -----------------------------------------------------------------


const KIND: Record<FilterKey, { label: string; icon: string }> = {
  all: { label: 'Entry', icon: 'article' },
  github: { label: 'GitHub repo', icon: 'code' },
  portfolio: { label: 'Portfolio', icon: 'language' },
  linkedin: { label: 'LinkedIn', icon: 'badge' },
  notes: { label: 'Your note', icon: 'edit_note' },
}

export function EntryCard({ entry, onEdit, onDelete, busy }: { entry: Evidence; onEdit: (c: { title?: string; text?: string; skills?: string[] }) => Promise<boolean>; onDelete: () => void; busy: boolean }) {
  const kind = KIND[sourceOf(entry)]
  const isNote = sourceOf(entry) === 'notes'
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(entry.title)
  const [text, setText] = useState(entry.text)
  const [skills, setSkills] = useState(entry.skills.join(', '))
  const shownTitle = sourceOf(entry) === 'github' && entry.url ? entry.url.replace(/^https?:\/\/github\.com\//, '') : entry.title

  const save = async () => {
    const ok = await onEdit(isNote ? { text } : { title, text, skills: skills.split(',').map((s) => s.trim()).filter(Boolean) })
    if (ok) setEditing(false)
  }

  return (
    <article className="group relative flex flex-col justify-between rounded-2xl border border-outline-variant/40 bg-surface-container-lowest p-space-lg shadow-sm transition-all hover:shadow-md">
      <div className="flex flex-col gap-space-md">
        <div className="flex items-start justify-between gap-space-sm">
          <div className="flex min-w-0 items-center gap-space-sm">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface-container">
              <Icon name={kind.icon} className="text-[20px] text-primary-container" />
            </div>
            <div className="flex min-w-0 flex-col">
              <span className="font-label-sm text-label-sm font-semibold uppercase tracking-wider text-primary">{kind.label}</span>
              {!isNote && (
                <span className="truncate font-code-sm text-code-sm font-medium text-on-surface transition-colors group-hover:text-primary-container">
                  {entry.url ? (
                    <a href={entry.url} target="_blank" rel="noreferrer" className="hover:underline">{shownTitle}</a>
                  ) : (
                    shownTitle
                  )}
                </span>
              )}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1 opacity-60 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
            <button type="button" aria-label="Edit entry" onClick={() => setEditing((e) => !e)} className="rounded-lg p-1 text-secondary transition-colors hover:bg-surface-container hover:text-on-surface">
              <Icon name="edit" className="text-[18px]" />
            </button>
            <button type="button" aria-label="Delete entry" disabled={busy} onClick={onDelete} className="rounded-lg p-1 text-secondary transition-colors hover:bg-surface-container hover:text-error">
              <Icon name="delete" className="text-[18px]" />
            </button>
          </div>
        </div>

        {editing ? (
          <div className="flex flex-col gap-2">
            {!isNote && <TextInput value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Title" placeholder="Title" />}
            <TextArea rows={5} value={text} onChange={(e) => setText(e.target.value)} aria-label="Text" />
            {!isNote && <TextInput value={skills} onChange={(e) => setSkills(e.target.value)} aria-label="Skills" placeholder="Skills, separated by commas" />}
            <div className="flex gap-2">
              <Button size="sm" onClick={save} loading={busy}>Save</Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
            </div>
          </div>
        ) : (
          <p className="line-clamp-5 font-body-md text-body-md leading-relaxed text-on-surface-variant">{entry.text || <span className="text-outline">No description</span>}</p>
        )}
      </div>
      {!editing && entry.skills.length > 0 && (
        <div className="mt-space-lg flex flex-wrap items-center gap-1.5 pt-space-md">
          {entry.skills.slice(0, 8).map((s) => (
            <span key={s} className="rounded-full bg-surface-container px-2.5 py-1 font-code-sm text-code-sm text-on-secondary-fixed-variant">{s}</span>
          ))}
        </div>
      )}
    </article>
  )
}

// --- the four ways to add context ----------------------------------------------------------------------

export function LinkAdder({ kind, k, autoFocus }: { kind: 'github' | 'portfolio'; k: Knowledge; autoFocus?: boolean }) {
  const [value, setValue] = useState('')
  const github = kind === 'github'
  const submit = async () => {
    if (await k.addLink(kind, value.trim())) setValue('')
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-2">
        <TextInput
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && value.trim() && submit()}
          autoFocus={autoFocus}
          placeholder={github ? 'github.com/yourname' : 'yourname.dev'}
          aria-label={github ? 'GitHub link' : 'Portfolio link'}
          spellCheck={false}
        />
        <Button variant="secondary" disabled={!value.trim() || !!k.busy} onClick={submit}>Read</Button>
      </div>
    </div>
  )
}

export function LinkedInAdder({ k }: { k: Knowledge }) {
  const ref = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) void k.addLinkedIn(f) }}
      className={`flex flex-col items-center gap-2 rounded-xl border-2 border-dashed px-4 py-5 text-center transition ${drag ? 'border-primary-container bg-primary-fixed/20' : 'border-outline-variant'}`}
    >
      <Icon name="upload_file" className="text-[26px] text-primary-container" />
      <div className="font-label-md text-label-md text-on-surface">Drop your LinkedIn PDF</div>
      <Button variant="secondary" size="sm" disabled={!!k.busy} onClick={() => ref.current?.click()}>Choose file</Button>
      <input ref={ref} type="file" accept=".pdf,application/pdf" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void k.addLinkedIn(f); e.target.value = '' }} />
    </div>
  )
}

export function NoteAdder({ k, rows = 4, inputRef }: { k: Knowledge; rows?: number; inputRef?: React.RefObject<HTMLTextAreaElement | null> }) {
  const [draft, setDraft] = useState('')
  const lines = noteLines(draft)
  const save = async () => {
    if (lines.length && (await k.addNotes(draft))) setDraft('')
  }
  return (
    <div className="flex flex-col gap-2">
      <TextArea
        ref={inputRef}
        rows={rows}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault()
            void save()
          }
        }}
        aria-label="Add notes about yourself"
        placeholder={"One fact or accomplishment per line, in your own words.\nAt Finch Payments I built Kafka consumers for settlement events\nWon 2nd place at DevHacks 2025 with a Flutter app"}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={!lines.length || !!k.busy} loading={k.busy === 'Saving…'} onClick={save}>
          <Icon name="save" className="text-[18px]" /> {lines.length ? `Save ${lines.length} ${lines.length === 1 ? 'note' : 'notes'}` : 'Save'}
        </Button>
        <span className="font-body-sm text-body-sm text-on-surface-variant">
          <kbd className="rounded bg-surface-container px-1.5 py-0.5 font-code-sm text-code-sm">⌘/Ctrl + Enter</kbd> also saves
        </span>
      </div>
    </div>
  )
}

export function Status({ k }: { k: Knowledge }) {
  return (
    <>
      {k.busy && k.busy !== 'Saving…' && <Notice tone="accent" icon="progress_activity">{k.busy}</Notice>}
      {k.error && <Notice tone="bad">{k.error}</Notice>}
      {k.message && !k.error && !k.busy && <Notice tone="good">{k.message}</Notice>}
    </>
  )
}

export function CountBadge({ n }: { n: number }) {
  return <Badge tone="accent">{n} {n === 1 ? 'entry' : 'entries'}</Badge>
}
