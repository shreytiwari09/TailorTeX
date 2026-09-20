import { useRef, useState } from 'react'
import type { Evidence } from '../api'
import { noteBlocks } from './format'
import { sourceOf, type FilterKey, type Knowledge } from './knowledge'
import { Badge, Button, Card, Icon, Notice, TextArea, TextInput } from './ui'

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

/** Everyone's repo list, so they choose what speaks for them instead of the app guessing. */
export function RepoPicker({ k }: { k: Knowledge }) {
  const choice = k.repoChoice
  // Keyed by the list, so a new list starts the picker fresh instead of an effect resetting it.
  return choice ? <RepoList key={`${choice.user}:${choice.repos.length}`} k={k} choice={choice} /> : null
}

function RepoList({ k, choice }: { k: Knowledge; choice: NonNullable<Knowledge['repoChoice']> }) {
  const [picked, setPicked] = useState<string[]>(() => choice.repos.slice(0, Math.min(6, choice.max)).map((r) => r.name))
  const [query, setQuery] = useState('')

  const full = picked.length >= choice.max
  const q = query.trim().toLowerCase()
  const shown = q ? choice.repos.filter((r) => `${r.name} ${r.description} ${r.language ?? ''}`.toLowerCase().includes(q)) : choice.repos
  const toggle = (name: string) => setPicked((p) => (p.includes(name) ? p.filter((x) => x !== name) : full ? p : [...p, name]))

  return (
    <Card className="flex flex-col gap-space-md p-space-lg">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-headline-sm text-headline-sm text-on-surface">Choose your repositories</h3>
          <p className="font-body-sm text-body-sm text-on-surface-variant">
            {choice.repos.length} public repositories under {choice.user}. Pick the ones you'd defend in an interview, up to {choice.max}.
          </p>
        </div>
        <Badge tone={full ? 'warn' : 'accent'}>{picked.length} of {choice.max}</Badge>
      </div>
      {choice.repos.length > 8 && (
        <TextInput value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter by name, description or language" aria-label="Filter repositories" spellCheck={false} />
      )}
      <ul className="-mx-1 flex max-h-[340px] flex-col gap-1 overflow-y-auto px-1">
        {shown.map((r) => {
          const on = picked.includes(r.name)
          return (
            <li key={r.name}>
              <label className={`flex cursor-pointer items-start gap-3 rounded-lg p-2.5 transition-colors ${on ? 'bg-primary-fixed/25' : 'hover:bg-surface-container-low'} ${!on && full ? 'opacity-50' : ''}`}>
                <input type="checkbox" checked={on} disabled={!on && full} onChange={() => toggle(r.name)} className="mt-1 h-4 w-4 shrink-0 accent-[var(--color-primary)]" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                    <span className="font-code-sm text-code-sm font-semibold text-on-surface">{r.name}</span>
                    {r.language && <Badge tone="neutral">{r.language}</Badge>}
                    {r.stars > 0 && <span className="inline-flex items-center gap-0.5 font-code-sm text-code-sm text-tertiary"><Icon name="star" fill className="text-[13px]" />{r.stars}</span>}
                    {r.pushed_at && <span className="font-code-sm text-code-sm text-outline">{r.pushed_at.slice(0, 7)}</span>}
                  </span>
                  {r.description && <span className="line-clamp-2 font-body-sm text-body-sm text-on-surface-variant">{r.description}</span>}
                </span>
              </label>
            </li>
          )
        })}
        {!shown.length && <li className="p-2.5 font-body-sm text-body-sm text-on-surface-variant">Nothing matches that.</li>}
      </ul>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-body-sm text-body-sm text-on-surface-variant">
          Each repository's README and languages are read. {full ? `That's the most GitHub allows in one go.` : ''}
        </span>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => k.setRepoChoice(null)}>Not now</Button>
          <Button disabled={!picked.length || !!k.busy} loading={!!k.busy} onClick={() => void k.pickRepos(picked)}>
            <Icon name="download" className="text-[18px]" /> Add {picked.length || ''}
          </Button>
        </div>
      </div>
    </Card>
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
  const blocks = noteBlocks(draft)
  const save = async () => {
    if (blocks.length && (await k.addNotes(draft))) setDraft('')
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
        placeholder={"Write about yourself in your own words: a project, a role, a win, or a post you've written.\n\nLeave a blank line between separate topics. Everything in one paragraph is kept together, so a long post stays whole."}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={!blocks.length || !!k.busy} loading={k.busy === 'Saving…'} onClick={save}>
          <Icon name="save" className="text-[18px]" /> {blocks.length ? `Save ${blocks.length} ${blocks.length === 1 ? 'entry' : 'entries'}` : 'Save'}
        </Button>
        <span className="font-body-sm text-body-sm text-on-surface-variant">
          A blank line starts a new entry · <kbd className="rounded bg-surface-container px-1.5 py-0.5 font-code-sm text-code-sm">⌘/Ctrl + Enter</kbd> saves
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
