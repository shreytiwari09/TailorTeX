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

const suggest = (g: GapGain, first = false): string =>
  `${first ? '' : 'Next: '}**${g.term}** (${g.must ? 'required' : 'nice to have'}, worth up to ${gainLabel(g.gain)} on your ATS score). Do you have it? Tell me in your own words: that you know it, something you built with it, or that you'd rather skip it.`

/**
 * A conversation about the skills the job asks for that nothing in the person's material shows.
 *
 * The assistant only proposes the next skill. Whatever the person types goes to it as it is, and it works out
 * what they mean and does it: put a skill on their Skills line, write up work they did, start a new project,
 * skip, or answer a question. There is no script here, and nothing decides what a message means on this side.
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
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [snippets, setSnippets] = useState<ProjectSnippet[]>([])
  const [manual, setManual] = useState<{ term: string; latex: string }[]>([])
  const [copied, setCopied] = useState<string | null>(null)
  const nextId = useRef(2)
  const [messages, setMessages] = useState<Msg[]>(() => {
    const first = gaps[0]
    return first
      ? [
          { id: 0, from: 'assistant', text: `The job asks for ${gaps.length === 1 ? 'a skill' : `${gaps.length} skills`} I couldn't find in your resume or context. I'll suggest them one at a time, most valuable first, but you steer: tell me any skill you have, something you built, or say skip. I only write what you tell me.` },
          { id: 1, from: 'assistant', text: suggest(first, true) },
        ]
      : []
  })
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [messages, drafted.length, snippets.length, manual.length, busy])

  const queue = gaps.filter((g) => !handled.includes(g.term))
  const current = queue[0] ?? null
  const total = gaps.length

  const push = (from: Msg['from'], text: string) => {
    const id = nextId.current++
    setMessages((m) => [...m, { id, from, text }])
    return id
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
      const r = await acct.chatRun(runId, text, history, current?.term ?? null, [...acceptedOps, ...drafted.map((d) => d.op)])
      push('assistant', r.reply)
      if (r.stored) onStored(r.evidence)
      if (r.ops.length) onDrafted(r)
      if (r.projects.length) setSnippets((s) => [...s, ...r.projects])
      if (r.manual.length) setManual((m) => [...m, ...r.manual])
      const done = [...new Set(r.handled)]
      if (done.length) {
        setHandled((h) => [...h, ...done.filter((t) => !h.includes(t))])
        // the assistant only proposes the next skill once the last one is dealt with, never in the middle of a question
        const next = gaps.find((g) => !handled.includes(g.term) && !done.some((d) => d.toLowerCase() === g.term.toLowerCase()))
        if (next && !r.needs_more) push('assistant', suggest(next))
        else if (!next) push('assistant', "That's every skill the job asked for that I couldn't find. You can still tell me anything else you'd like on your resume.")
      }
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
  return (
    <Card className="flex flex-col gap-space-md p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 font-headline-sm text-headline-sm text-on-surface">
            Talk to your resume
            <InfoTip align="left">
              The job asks for skills that aren't written anywhere in your resume or context. Tell the assistant what you know in your own words: that you have a skill (no project needed), something you built, or that you want to skip it. It works out what you mean and does it. It only uses what you say.
            </InfoTip>
          </h2>
          <p className="mt-0.5 font-body-sm text-body-sm text-on-surface-variant">Say anything about your skills. What you tell it becomes part of your context.</p>
        </div>
        {total > 0 && <Badge tone="accent">{Math.min(handled.length + 1, total)} of {total}</Badge>}
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

      {!hasModel && total > 0 && <Notice tone="warn">Add a model key in Settings first: the assistant needs one to understand you.</Notice>}

      {total > 0 && (
        <div className="flex max-h-[560px] flex-col gap-2.5 overflow-y-auto rounded-xl bg-surface-container-lowest p-1" aria-live="polite">
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
            aria-label="Tell the assistant about your skills"
            placeholder={current ? `Tell me about ${current.term}, or anything else you'd like on your resume…` : 'Anything else you would like on your resume…'}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" loading={busy} disabled={!input.trim() || !hasModel}><Icon name="send" className="text-[17px]" /> Send</Button>
            {current && <Button type="button" variant="ghost" disabled={busy || !hasModel} onClick={() => void submit(`skip ${current.term}`)}>Skip {current.term}</Button>}
            <span className="font-body-sm text-body-sm text-on-surface-variant">Enter to send, Shift+Enter for a new line</span>
          </div>
        </form>
      )}
    </Card>
  )
}
