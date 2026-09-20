import { useMemo, useRef, useState } from 'react'
import { useAuth } from '../auth'
import { EntryCard, LinkAdder, LinkedInAdder, NoteAdder, RepoPicker, Status } from '../context'
import { timeAgo } from '../format'
import { sourceOf, useKnowledge, type FilterKey } from '../knowledge'
import { Badge, Button, Card, Icon, InfoTip, Skeleton, TextInput } from '../ui'

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'github', label: 'GitHub' },
  { key: 'portfolio', label: 'Portfolio' },
  { key: 'linkedin', label: 'LinkedIn' },
  { key: 'notes', label: 'Notes' },
]

export function ContextPage() {
  const k = useKnowledge()
  const { profile } = useAuth()
  const [filter, setFilter] = useState<FilterKey>('all')
  const [query, setQuery] = useState('')
  const [panel, setPanel] = useState<null | 'github' | 'portfolio' | 'linkedin'>(null)
  const noteRef = useRef<HTMLTextAreaElement>(null)
  const [skill, setSkill] = useState('')

  const counts = useMemo(() => {
    const c: Record<FilterKey, number> = { all: k.entries.length, github: 0, portfolio: 0, linkedin: 0, notes: 0 }
    for (const e of k.entries) c[sourceOf(e)]++
    return c
  }, [k.entries])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return k.entries.filter((e) => (filter === 'all' || sourceOf(e) === filter) && (!q || `${e.title} ${e.text} ${e.skills.join(' ')}`.toLowerCase().includes(q)))
  }, [k.entries, filter, query])

  const addSkill = () => {
    const next = [...k.skills]
    for (const s of skill.split(/[,\n]/).map((x) => x.trim()).filter(Boolean)) if (!next.some((x) => x.toLowerCase() === s.toLowerCase())) next.push(s)
    void k.saveSkills(next)
    setSkill('')
  }

  return (
    <div className="flex flex-col gap-space-xl">
      <div className="flex flex-col justify-between gap-space-lg lg:flex-row lg:items-end">
        <div className="flex max-w-2xl flex-col gap-space-sm">
          <div className="flex items-center gap-space-md">
            <h1 className="font-headline-lg-mobile text-headline-lg-mobile tracking-tight text-on-surface md:font-headline-lg md:text-headline-lg">My context</h1>
            <InfoTip align="left">
              This is your private knowledge base. TailorTeX searches it by meaning, not just keywords, so “event streaming” finds your Kafka note. Only what's here can be added to a resume.
            </InfoTip>
          </div>
          <div className="flex flex-wrap items-center gap-space-sm">
            <Badge tone="accent" className="gap-2 px-3 py-1 font-semibold">
              <span className="h-2 w-2 rounded-full bg-primary-container" />
              {counts.all} {counts.all === 1 ? 'entry' : 'entries'} in your knowledge base
            </Badge>
            {profile?.updated_at && <span className="font-body-sm text-body-sm text-on-surface-variant">Updated {timeAgo(profile.updated_at)}</span>}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-space-sm">
          <AddPill icon="terminal" label="GitHub" active={panel === 'github'} onClick={() => setPanel(panel === 'github' ? null : 'github')} />
          <AddPill icon="language" label="Portfolio" active={panel === 'portfolio'} onClick={() => setPanel(panel === 'portfolio' ? null : 'portfolio')} />
          <AddPill icon="description" label="LinkedIn PDF" active={panel === 'linkedin'} onClick={() => setPanel(panel === 'linkedin' ? null : 'linkedin')} />
          <Button size="sm" onClick={() => { setPanel(null); noteRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }); noteRef.current?.focus() }}>
            <Icon name="edit_note" className="text-[18px]" /> Add quick note
          </Button>
        </div>
      </div>

      {panel && (
        <Card className="p-space-lg">
          <div className="mb-3 font-label-md text-label-md font-semibold text-on-surface">
            {panel === 'github' ? 'Add your GitHub' : panel === 'portfolio' ? 'Add your portfolio' : 'Add your LinkedIn PDF'}
          </div>
          {panel === 'linkedin' ? <LinkedInAdder k={k} /> : <LinkAdder kind={panel} k={k} autoFocus />}
          <p className="mt-2 font-body-sm text-body-sm text-on-surface-variant">
            {panel === 'github' ? 'All your public repositories are read. If you have more than 10, you choose which ones count.' : panel === 'portfolio' ? 'The page is read once, and your projects and skills become entries.' : 'On LinkedIn, open your profile and click More → Save to PDF.'}
          </p>
        </Card>
      )}
      <Status k={k} />
      <RepoPicker k={k} />

      <div className="flex flex-col items-stretch justify-between gap-space-md rounded-2xl bg-surface-container-low p-2 shadow-sm md:flex-row md:items-center">
        <div className="relative min-w-0 flex-1">
          <Icon name="search" className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[20px] text-tertiary" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter your entries, e.g. Kafka"
            aria-label="Filter entries"
            className="w-full rounded-xl bg-surface-container-lowest py-2.5 pl-10 pr-4 font-body-sm text-body-sm text-on-surface shadow-sm outline-none transition-all placeholder:text-tertiary focus:ring-2 focus:ring-primary-container/20"
          />
        </div>
        <div role="tablist" aria-label="Source" className="flex items-center gap-1 overflow-x-auto p-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              role="tab"
              aria-selected={filter === f.key}
              onClick={() => setFilter(f.key)}
              className={`whitespace-nowrap rounded-full px-3.5 py-1.5 font-label-sm text-label-sm transition-all ${filter === f.key ? 'bg-surface-container font-semibold text-on-surface' : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'}`}
            >
              {f.label} <span className="ml-1 font-code-sm text-code-sm opacity-70">{counts[f.key]}</span>
            </button>
          ))}
        </div>
      </div>

      {k.loading ? (
        <div className="grid grid-cols-1 gap-space-lg md:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-48" />)}
        </div>
      ) : shown.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 px-6 py-space-2xl text-center">
          <Icon name="inventory_2" className="text-[36px] text-outline" />
          <div className="font-headline-sm text-headline-sm text-on-surface">{counts.all ? 'No entries match' : 'Nothing here yet'}</div>
          <p className="max-w-md font-body-md text-body-md text-on-surface-variant">
            {counts.all ? 'Try a different filter or search.' : 'Add your GitHub, portfolio or LinkedIn, or write a note. TailorTeX can only add what is backed here.'}
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-space-lg md:grid-cols-2 lg:grid-cols-3">
          {shown.map((e) => (
            <EntryCard key={e.id} entry={e} busy={!!k.busy} onEdit={(c) => k.editEntry(e, c)} onDelete={() => void k.removeEntry(e)} />
          ))}
        </div>
      )}

      <Card className="p-space-lg">
        <div className="mb-3 flex items-center gap-2">
          <span className="font-label-md text-label-md font-semibold text-on-surface">Skills you can defend</span>
          <InfoTip>Skills you could talk about in an interview. They can go into your skills lines and summary, never into a specific job's bullets.</InfoTip>
        </div>
        <div className="mb-3 flex flex-wrap gap-1.5">
          {k.skills.length === 0 && <span className="font-body-sm text-body-sm text-on-surface-variant">None yet.</span>}
          {k.skills.map((s) => (
            <span key={s} className="inline-flex items-center gap-1 rounded-full bg-surface-container py-1 pl-3 pr-1.5 font-code-sm text-code-sm text-on-secondary-fixed-variant">
              {s}
              <button type="button" aria-label={`Remove ${s}`} onClick={() => void k.saveSkills(k.skills.filter((x) => x !== s))} className="rounded-full p-0.5 hover:bg-surface-container-high">
                <Icon name="close" className="text-[14px]" />
              </button>
            </span>
          ))}
        </div>
        <div className="flex max-w-md gap-2">
          <TextInput value={skill} onChange={(e) => setSkill(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && skill.trim() && addSkill()} placeholder="e.g. AWS, Kafka" aria-label="Add a skill" />
          <Button variant="secondary" disabled={!skill.trim()} onClick={addSkill}>Add</Button>
        </div>
      </Card>

      <Card className="p-space-lg shadow-md">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-primary-container" />
            <span className="font-label-md text-label-md font-semibold text-on-surface">Quick note</span>
            <InfoTip>Say where something happened so it lands under the right job. Numbers are used exactly as you write them.</InfoTip>
          </div>
          <span className="font-body-sm text-body-sm text-on-surface-variant">Indexed for matching by meaning as soon as you save</span>
        </div>
        <NoteAdder k={k} inputRef={noteRef} />
      </Card>
    </div>
  )
}

function AddPill({ icon, label, active, onClick }: { icon: string; label: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" aria-pressed={active} onClick={onClick} className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 font-label-sm text-label-sm text-on-surface shadow-sm transition-all ${active ? 'bg-surface-container' : 'bg-surface-container-low hover:bg-surface-container'}`}>
      <Icon name={icon} className="text-[18px] text-primary-container" />
      <span>+ {label}</span>
    </button>
  )
}
