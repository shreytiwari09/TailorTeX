import { useState } from 'react'
import type { Change, Evidence, GapGain, Op } from '../../api'
import { plain } from '../../util'
import { acct, type AnswerIn, type AnswerResult, type ProjectSnippet } from '../client'
import { gainLabel } from '../format'
import { Badge, Button, Card, Icon, InfoTip, Notice, TextArea, TextInput } from '../ui'
import { ProjectSnippetCard } from './ProjectSnippetCard'

export type Entry = { id: string; label: string }

/** A drafted bullet the person has not yet accepted. */
export type Drafted = { op: Op; change: Change }

/**
 * Skills the job asks for that nothing in the resume or context shows.
 *
 * TailorTeX won't write a claim nobody supplied, so instead of leaving these out silently it asks.
 * Whatever the person writes, a line or a paragraph, is kept as permanent context and used to draft
 * a bullet, which is checked against their own words: it can only name what they said.
 */
export function AdvancedPanel({ runId, gaps, entries, acceptedOps, onDrafted, drafted, onAccept, onDiscard, onStored, hasModel, engine, filename }: {
  runId: string
  gaps: GapGain[]
  entries: Entry[]
  acceptedOps: Op[]
  drafted: Drafted[]
  onDrafted: (r: AnswerResult) => void
  onAccept: (d: Drafted) => void
  onDiscard: (d: Drafted) => void
  onStored: (e: Evidence[]) => void
  hasModel: boolean
  engine: string
  filename: string
}) {
  const [open, setOpen] = useState<string | null>(null)
  const [text, setText] = useState<Record<string, string>>({})
  const [target, setTarget] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [followups, setFollowups] = useState<Record<string, string>>({})
  const [rejected, setRejected] = useState<{ term: string; message: string }[]>([])
  // Was it inside a job or project already on the resume, or a separate project?
  const [kind, setKind] = useState<Record<string, 'entry' | 'project'>>({})
  const [name, setName] = useState<Record<string, string>>({})
  const [dates, setDates] = useState<Record<string, string>>({})
  const [tech, setTech] = useState<Record<string, string>>({})
  const [snippets, setSnippets] = useState<ProjectSnippet[]>([])

  const total = gaps.reduce((n, g) => n + g.gain, 0)
  const isProject = (term: string) => kind[term] === 'project'
  const ready = gaps.filter((g) => (text[g.term] ?? '').trim().length >= 12 && (!isProject(g.term) || (name[g.term] ?? '').trim().length >= 2))

  const send = async () => {
    setBusy(true)
    setError(null)
    setRejected([])
    try {
      const answers: AnswerIn[] = ready.map((g) => ({
        term: g.term,
        text: text[g.term].trim(),
        target: isProject(g.term) ? null : target[g.term] || null,
        project: isProject(g.term)
          ? { name: name[g.term].trim(), dates: (dates[g.term] ?? '').trim(), tech: (tech[g.term] ?? g.term).split(',').map((t) => t.trim()).filter(Boolean) }
          : null,
      }))
      const r = await acct.answerRun(runId, answers, acceptedOps)
      onDrafted(r)
      setSnippets((list) => [...list, ...r.projects])
      onStored(r.evidence)
      setFollowups(Object.fromEntries(r.followups.map((f) => [f.term, f.question])))
      setRejected(r.blocked.map((b) => ({ term: b.text ?? b.op, message: b.message })))
      // what became a bullet is done; what came back as a question stays open
      setText((t) => Object.fromEntries(Object.entries(t).filter(([term]) => r.followups.some((f) => f.term === term))))
      setOpen(r.followups[0]?.term ?? null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  if (!gaps.length && !drafted.length && !snippets.length) return null
  return (
    <Card className="flex flex-col gap-space-md p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 font-headline-sm text-headline-sm text-on-surface">
            Skills the job wants that we can't find
            <InfoTip align="left">
              We won't write something nobody told us. If you have done any of these, say so, in a line or a paragraph: what you built, with what, and what changed. We'll write the bullet from your words, and it can only use what you said.
              If you haven't, leave it: adding it wouldn't survive an interview.
            </InfoTip>
          </h2>
          {gaps.length > 0 && (
            <p className="mt-0.5 font-body-sm text-body-sm text-on-surface-variant">
              Backing these could add up to <strong className="text-on-surface">{gainLabel(total)}</strong> to your ATS score. Only fill in the ones that are true.
            </p>
          )}
        </div>
        {gaps.length > 0 && <Badge tone="accent">{gaps.length} {gaps.length === 1 ? 'skill' : 'skills'}</Badge>}
      </div>

      {!hasModel && <Notice tone="warn">Add a model key in Settings first: writing the bullet from your answer needs one.</Notice>}
      {error && <Notice tone="bad">{error}</Notice>}
      {rejected.length > 0 && (
        <Notice tone="warn">
          One draft mentioned something you didn't say, so it was left out: {rejected[0].message} Add the detail to your answer and try again.
        </Notice>
      )}

      {snippets.map((sn) => (
        <ProjectSnippetCard key={sn.answer} snippet={sn} engine={engine} filename={filename} onDismiss={() => setSnippets((l) => l.filter((x) => x !== sn))} />
      ))}

      {drafted.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="font-label-md text-label-md font-semibold uppercase tracking-wider text-on-surface-variant">Written from what you told us</h3>
          {drafted.map((d) => (
            <div key={d.change.id} className="flex flex-col gap-2 rounded-xl border border-emerald-200 bg-emerald-50/50 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="good">New bullet</Badge>
                <span className="font-code-sm text-code-sm text-on-surface-variant">{[d.change.section, d.change.heading].filter(Boolean).join(' › ')}</span>
                {(d.change.gain ?? 0) > 0 && <span className="ml-auto rounded bg-emerald-100 px-1.5 py-0.5 font-code-sm text-[11px] font-semibold text-emerald-800">{gainLabel(d.change.gain ?? 0)} ATS</span>}
              </div>
              <p className="font-body-md text-body-md leading-relaxed text-on-surface">{plain(d.change.after)}</p>
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" onClick={() => onAccept(d)}><Icon name="check" className="text-[16px]" /> Add to my resume</Button>
                <Button size="sm" variant="ghost" onClick={() => onDiscard(d)}>Not this one</Button>
                <span className="font-body-sm text-body-sm text-on-surface-variant">Uses only what you wrote.</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <ul className="flex flex-col divide-y divide-outline-variant/40">
        {gaps.map((g) => {
          const isOpen = open === g.term
          const q = followups[g.term]
          return (
            <li key={g.term} className="py-3 first:pt-0 last:pb-0">
              <button type="button" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : g.term)} className="flex w-full items-center justify-between gap-3 text-left">
                <span className="flex items-center gap-2">
                  <span className="font-label-md text-label-md font-semibold text-on-surface">{g.term}</span>
                  {g.must ? <Badge tone="neutral">required</Badge> : <span className="font-body-sm text-body-sm text-on-surface-variant">nice to have</span>}
                </span>
                <span className="flex items-center gap-2">
                  <span className="rounded bg-primary-fixed/40 px-1.5 py-0.5 font-code-sm text-[11px] font-semibold text-primary">up to {gainLabel(g.gain)}</span>
                  <Icon name={isOpen ? 'expand_less' : 'expand_more'} className="text-[18px] text-on-surface-variant" />
                </span>
              </button>
              {isOpen && (
                <div className="mt-3 flex flex-col gap-2">
                  {q && <Notice tone="accent" icon="help">{q}</Notice>}
                  <TextArea
                    rows={4}
                    value={text[g.term] ?? ''}
                    onChange={(e) => setText((t) => ({ ...t, [g.term]: e.target.value }))}
                    aria-label={`What you have done with ${g.term}`}
                    placeholder={`Anything about ${g.term}: a project, a course, something you built at work. One line or a paragraph. What you did, what you used, what changed.`}
                  />
                  <div role="radiogroup" aria-label={`Where did you use ${g.term}?`} className="flex flex-wrap gap-2">
                    {([['entry', 'In a job or project already on my resume'], ['project', "It was a separate project"]] as const).map(([k, label]) => (
                      <button
                        key={k}
                        type="button"
                        role="radio"
                        aria-checked={(kind[g.term] ?? 'entry') === k}
                        onClick={() => setKind((x) => ({ ...x, [g.term]: k }))}
                        className={`rounded-full border px-3 py-1 font-label-sm text-label-sm transition-colors ${(kind[g.term] ?? 'entry') === k ? 'border-primary-container bg-primary-fixed/40 text-primary' : 'border-outline-variant text-on-surface-variant hover:bg-surface-container-low'}`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  {isProject(g.term) && (
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <TextInput value={name[g.term] ?? ''} onChange={(e) => setName((x) => ({ ...x, [g.term]: e.target.value }))} placeholder="Project name" aria-label="Project name" />
                      <TextInput value={dates[g.term] ?? ''} onChange={(e) => setDates((x) => ({ ...x, [g.term]: e.target.value }))} placeholder="When, e.g. Jan 2026 - Apr 2026" aria-label="Project dates" />
                      <TextInput className="sm:col-span-2" value={tech[g.term] ?? g.term} onChange={(e) => setTech((x) => ({ ...x, [g.term]: e.target.value }))} placeholder="Technologies, separated by commas" aria-label="Technologies" />
                    </div>
                  )}
                  {entries.length > 0 && !isProject(g.term) && (
                    <label className="flex flex-wrap items-center gap-2 font-body-sm text-body-sm text-on-surface-variant">
                      Where does this belong?
                      <select
                        value={target[g.term] ?? ''}
                        onChange={(e) => setTarget((t) => ({ ...t, [g.term]: e.target.value }))}
                        className="rounded-lg border border-outline-variant bg-surface-container-lowest px-2 py-1 font-body-sm text-body-sm text-on-surface"
                      >
                        <option value="">Let TailorTeX choose</option>
                        {entries.map((e) => <option key={e.id} value={e.id}>{e.label}</option>)}
                      </select>
                    </label>
                  )}
                </div>
              )}
            </li>
          )
        })}
      </ul>

      {gaps.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-3">
            <Button loading={busy} disabled={!ready.length || !hasModel} onClick={send}>
              <Icon name="edit_note" className="text-[18px]" /> Write {ready.length || ''} {ready.length === 1 ? 'bullet' : 'bullets'} from my answers
            </Button>
            <span className="font-body-sm text-body-sm text-on-surface-variant">
              {ready.length ? `${ready.length} ready` : 'Write at least a sentence about one skill'}. Your answers are saved to My context, so future resumes can use them.
            </span>
          </div>
          <p className="font-body-sm text-body-sm text-on-surface-variant">
            For a job or project you already have, this adds a bullet to it. For a separate project, TailorTeX can't add a new entry itself, so you get code to paste into Projects in Overleaf.
          </p>
        </div>
      )}
    </Card>
  )
}
