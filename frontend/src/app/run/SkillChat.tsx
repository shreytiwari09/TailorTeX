import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import type { Change, Evidence, GapGain, Inferred, Op } from '../../api'
import { plain } from '../../util'
import { acct, type ChatResult, type ProjectSnippet } from '../client'
import { gainLabel } from '../format'
import { Badge, Button, Card, Icon, InfoTip, Notice, TextArea } from '../ui'
import { ProjectSnippetCard } from './ProjectSnippetCard'

/** A change the assistant made from what the person said, waiting for them to add it to the resume. */
export type Drafted = { op: Op; change: Change }

type Msg = { id: number; from: 'assistant' | 'you'; text: string }

/** **bold** in a message, and nothing else, so a message can't inject markup. */
function say(text: string): ReactNode {
  return text.split('**').map((part, i) => (i % 2 ? <strong key={i} className="font-semibold">{part}</strong> : <Fragment key={i}>{part}</Fragment>))
}

/**
 * Everything this job asks for that the person's material doesn't show, in one place.
 *
 * The list comes first and all of it at once, so they can see the whole ask and deal with it in one go:
 * tick the skills they have and put them on their Skills lines in a click, which is a plain edit to their
 * LaTeX and needs no model. The conversation underneath is for everything that deserves more than a list
 * entry: work they did, a project worth writing up, or a question.
 */
export function SkillChat({ runId, gaps, inferred, acceptedOps, drafted, hasModel, engine, filename, onDrafted, onAccept, onDiscard, onStored }: {
  runId: string
  gaps: GapGain[]
  inferred: Inferred[]
  acceptedOps: Op[]
  drafted: Drafted[]
  hasModel: boolean
  engine: string
  filename: string
  onDrafted: (r: Pick<ChatResult, 'ops' | 'changes'>) => void
  onAccept: (d: Drafted) => void
  onDiscard: (d: Drafted) => void
  onStored: (e: Evidence[]) => void
}) {
  const [handled, setHandled] = useState<string[]>([])
  const [ticked, setTicked] = useState<string[]>(() => gaps.map((g) => g.term))
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [adding, setAdding] = useState(false)
  const [snippets, setSnippets] = useState<ProjectSnippet[]>([])
  const [manual, setManual] = useState<{ term: string; latex: string }[]>([])
  const [copied, setCopied] = useState<string | null>(null)
  const nextId = useRef(1)
  const [messages, setMessages] = useState<Msg[]>(() =>
    gaps.length
      ? [{ id: 0, from: 'assistant', text: "Tick anything above that you have and add it in one go. If you actually built something with one of them, tell me here instead: a skill inside a bullet is worth more to an ATS than one in a list, and I'll write the bullet from your own words." }]
      : [])
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [messages, drafted.length, snippets.length, manual.length, busy])

  const open = gaps.filter((g) => !handled.includes(g.term))
  const chosen = open.filter((g) => ticked.includes(g.term))
  const total = gaps.length

  const push = (from: Msg['from'], text: string) => {
    const id = nextId.current++
    setMessages((m) => [...m, { id, from, text }])
    return id
  }

  const done = (terms: string[]) => setHandled((h) => [...h, ...terms.filter((t) => !h.includes(t))])

  /** Put the ticked skills on the Skills lines. A plain edit to their LaTeX: no model is asked anything. */
  const addTicked = async () => {
    if (!chosen.length || adding) return
    setAdding(true)
    try {
      const r = await acct.addSkills(runId, chosen.map((g) => g.term), acceptedOps)
      if (r.ops.length) onDrafted(r)
      if (r.manual.length) setManual((m) => [...m, ...r.manual])
      if (r.skills_confirmed.length) push('assistant', `Put ${r.skills_confirmed.join(', ')} on your Skills lines. Add the change below to your resume, then Apply.`)
      for (const n of r.notes) if (!r.skills_confirmed.length) push('assistant', n)
      done(chosen.map((g) => g.term))
    } catch (e) {
      push('assistant', e instanceof Error ? e.message : 'Could not add those.')
    } finally {
      setAdding(false)
    }
  }

  const submit = async (raw: string) => {
    const text = raw.trim()
    if (!text || busy) return
    setInput('')
    const history = messages.map((m) => ({ role: m.from, text: m.text }))
    push('you', text)
    setBusy(true)
    try {
      // what is waiting to be added counts too, so a second skill on the same line builds on the first
      const r = await acct.chatRun(runId, text, history, null, [...acceptedOps, ...drafted.map((d) => d.op)])
      push('assistant', r.reply)
      if (r.stored) onStored(r.evidence)
      if (r.ops.length) onDrafted(r)
      if (r.projects.length) setSnippets((s) => [...s, ...r.projects])
      if (r.manual.length) setManual((m) => [...m, ...r.manual])
      done([...new Set(r.handled)])
    } catch (e) {
      push('assistant', e instanceof Error ? e.message : 'Something went wrong. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const copy = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(code)
      setTimeout(() => setCopied(null), 1800)
    } catch {
      /* the code is selectable, so it can still be copied by hand */
    }
  }

  if (!gaps.length && !inferred.length && !drafted.length && !snippets.length) return null
  const worth = chosen.reduce((n, g) => n + g.gain * 0.6, 0) // a skill in a list counts for less than one in a bullet

  return (
    <Card className="flex flex-col gap-space-md p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 font-headline-sm text-headline-sm text-on-surface">
            What this job asks for and your resume doesn't show
            <InfoTip align="left">
              Tick the ones you have: they go on your Skills lines, which is a plain edit to your LaTeX. For anything you actually built, tell the assistant instead, and it writes a bullet from your own words. It only ever writes what you tell it.
            </InfoTip>
          </h2>
          <p className="mt-0.5 font-body-sm text-body-sm text-on-surface-variant">{open.length} of {total} still open. Everything you confirm is kept for your next resume too.</p>
        </div>
        {total > 0 && <Badge tone="accent">{total - open.length} of {total} done</Badge>}
      </div>

      {inferred.length > 0 && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-3.5">
          <p className="flex items-center gap-1.5 font-label-md text-label-md font-semibold text-emerald-900">
            <Icon name="check_circle" fill className="text-[17px] text-emerald-600" /> Already shown in your own material, so I didn't need to ask
          </p>
          <ul className="mt-1.5 flex flex-col gap-1">
            {inferred.map((s) => (
              <li key={s.term} className="font-body-sm text-body-sm text-on-surface">
                <strong>{s.term}</strong>: “{s.quote}” <span className="text-on-surface-variant">({s.origin})</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {open.length > 0 && (
        <div className="flex flex-col gap-2 rounded-xl border border-outline-variant/60 p-3.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-label-md text-label-md font-semibold text-on-surface">Tick everything you have</p>
            <div className="flex gap-1">
              <Button size="sm" variant="ghost" onClick={() => setTicked(gaps.map((g) => g.term))}>All</Button>
              <Button size="sm" variant="ghost" onClick={() => setTicked([])}>None</Button>
            </div>
          </div>
          <ul className="flex flex-col">
            {open.map((g) => (
              <li key={g.term}>
                <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-1.5 py-1.5 hover:bg-surface-container-low">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-[var(--md-sys-color-primary,#1a56db)]"
                    checked={ticked.includes(g.term)}
                    onChange={(e) => setTicked((t) => (e.target.checked ? [...t, g.term] : t.filter((x) => x !== g.term)))}
                  />
                  <span className="font-body-md text-body-md text-on-surface">{g.term}</span>
                  <span className="font-body-sm text-body-sm text-on-surface-variant">{g.must ? 'required' : 'nice to have'}</span>
                  <span className="ml-auto font-code-sm text-code-sm text-on-surface-variant">up to {gainLabel(g.gain)}</span>
                </label>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" loading={adding} disabled={!chosen.length} onClick={() => void addTicked()}>
              <Icon name="playlist_add" className="text-[17px]" /> Add {chosen.length || ''} to my Skills{worth > 0.0004 ? ` (${gainLabel(worth)})` : ''}
            </Button>
            <Button size="sm" variant="ghost" disabled={!chosen.length} onClick={() => done(chosen.map((g) => g.term))}>Skip these</Button>
          </div>
          <p className="font-body-sm text-body-sm text-on-surface-variant">
            Adding a skill to a list is honest only if you have it. For the ones you built something with, say so below: in a bullet they are worth close to {gainLabel(chosen.reduce((n, g) => n + g.gain, 0))} instead.
          </p>
        </div>
      )}

      {!hasModel && total > 0 && <Notice tone="warn">Add a model key in Settings to talk to the assistant. Ticking skills above works without one.</Notice>}

      {total > 0 && (
        <div className="flex max-h-[460px] flex-col gap-2.5 overflow-y-auto rounded-xl bg-surface-container-lowest p-1" aria-live="polite">
          {messages.map((m) => (
            <div key={m.id} className={`max-w-[92%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 font-body-md text-body-md leading-relaxed ${m.from === 'assistant' ? 'self-start rounded-tl-sm bg-surface-container-low text-on-surface' : 'self-end rounded-tr-sm bg-primary text-on-primary'}`}>
              {m.from === 'assistant' ? say(m.text) : m.text}
            </div>
          ))}
          {busy && <div className="self-start rounded-2xl rounded-tl-sm bg-surface-container-low px-3.5 py-2.5 font-body-md text-body-md text-on-surface-variant"><Icon name="progress_activity" className="animate-spin text-[16px]" /> Thinking…</div>}

          {manual.map((m) => (
            <div key={m.term} className="flex flex-col gap-2 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
              <p className="font-body-md text-body-md text-on-surface">Add <strong>{m.term}</strong> to your Skills section in Overleaf, in the same style as the others:</p>
              <div className="flex items-center gap-2">
                <code className="flex-1 rounded-lg bg-surface-container-low px-3 py-2 font-code-sm text-code-sm text-on-surface">{m.latex}</code>
                <Button size="sm" variant="secondary" onClick={() => void copy(m.latex)}><Icon name={copied === m.latex ? 'check' : 'content_copy'} className="text-[16px]" /> {copied === m.latex ? 'Copied' : 'Copy'}</Button>
              </div>
            </div>
          ))}
          {snippets.map((sn) => (
            <ProjectSnippetCard key={sn.answer} snippet={sn} engine={engine} filename={filename} onDismiss={() => setSnippets((l) => l.filter((x) => x !== sn))} />
          ))}
          {drafted.map((d) => (
            <div key={`${d.change.id}-${d.op.target}-${d.op.text}`} className="flex flex-col gap-2 rounded-xl border border-emerald-200 bg-emerald-50/50 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="good">{d.op.op === 'add' ? 'New bullet' : 'Skills updated'}</Badge>
                <span className="font-code-sm text-code-sm text-on-surface-variant">{[d.change.section, d.change.heading || d.change.target].filter(Boolean).join(' › ')}</span>
                {(d.change.gain ?? 0) > 0 && <span className="ml-auto rounded bg-emerald-100 px-1.5 py-0.5 font-code-sm text-[11px] font-semibold text-emerald-800">{gainLabel(d.change.gain ?? 0)} ATS</span>}
              </div>
              <p className="font-body-md text-body-md leading-relaxed text-on-surface">{plain(d.change.after)}</p>
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" onClick={() => onAccept(d)}><Icon name="check" className="text-[16px]" /> Add to my resume</Button>
                <Button size="sm" variant="ghost" onClick={() => onDiscard(d)}>Not this one</Button>
              </div>
            </div>
          ))}
          <div ref={end} />
        </div>
      )}

      {total > 0 && (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            void submit(input)
          }}
        >
          <TextArea
            rows={2}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void submit(input)
              }
            }}
            disabled={!hasModel || busy}
            aria-label="Tell the assistant what you built"
            placeholder={open.length ? `Built something with ${open[0].term}? Tell me what you did, in your own words…` : 'Anything else you would like on your resume…'}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" loading={busy} disabled={!input.trim() || !hasModel}><Icon name="send" className="text-[17px]" /> Send</Button>
            <span className="font-body-sm text-body-sm text-on-surface-variant">Enter to send, Shift+Enter for a new line</span>
          </div>
        </form>
      )}
    </Card>
  )
}
