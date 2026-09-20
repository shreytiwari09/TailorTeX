import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react'
import type { Change, Evidence, GapGain, Inferred, Op } from '../../api'
import { plain } from '../../util'
import { acct, type AnswerResult, type ProjectSnippet } from '../client'
import { gainLabel } from '../format'
import { Badge, Button, Card, Icon, InfoTip, Notice, TextArea } from '../ui'
import { ProjectSnippetCard } from './ProjectSnippetCard'

/** A drafted bullet the person has not yet added to their resume. */
export type Drafted = { op: Op; change: Change }

type Msg = { id: number; from: 'assistant' | 'you'; body: ReactNode }

const SKIP = /^\s*(no+|nope|nah|not really|never|skip|pass|n\/a|none|haven'?t|have not|i haven'?t|i have not|i don'?t( have| know)?|i didn'?t)\b/i

/** **bold** in a message, and nothing else, so a message can't inject markup. */
function say(text: string): ReactNode {
  return text.split('**').map((part, i) => (i % 2 ? <strong key={i} className="font-semibold">{part}</strong> : <Fragment key={i}>{part}</Fragment>))
}

const ask = (g: GapGain): string =>
  `**${g.term}** (${g.must ? 'required' : 'nice to have'}): backing it is worth up to ${gainLabel(g.gain)} on your ATS score. Have you worked with it? Tell me what you built, what you used and what came of it. A sentence is enough. If you haven't, just say so and we'll move on.`

/**
 * The skills the job asks for that nothing in the person's material shows, as a conversation.
 *
 * One skill at a time, most valuable first. Whatever the person replies is kept as permanent context and
 * turned into what it should become: a bullet on a job or project they already have, or code for a
 * separate project. The server decides which, and the drafts are checked against the person's own words.
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
  onDrafted: (r: AnswerResult) => void
  onAccept: (d: Drafted) => void
  onDiscard: (d: Drafted) => void
  onStored: (e: Evidence[]) => void
}) {
  const [handled, setHandled] = useState<string[]>([])
  const [pending, setPending] = useState('') // what they've said so far about the current skill
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [snippets, setSnippets] = useState<ProjectSnippet[]>([])
  const nextId = useRef(2)
  const [messages, setMessages] = useState<Msg[]>(() => {
    const first = gaps[0]
    return first
      ? [
          { id: 0, from: 'assistant', body: say(`I couldn't find ${gaps.length === 1 ? 'a skill' : `${gaps.length} skills`} this job asks for anywhere in your resume or context. I'll ask about them one at a time, most valuable first. Answer in your own words, or skip any you haven't done. I'll only write what you tell me.`) },
          { id: 1, from: 'assistant', body: say(ask(first)) },
        ]
      : []
  })
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [messages, drafted.length, snippets.length, busy])

  const queue = gaps.filter((g) => !handled.includes(g.term))
  const current = queue[0] ?? null
  const total = gaps.length

  const push = (from: Msg['from'], body: ReactNode) => setMessages((m) => [...m, { id: nextId.current++, from, body }])
  const moveOn = (done: string) => {
    const remaining = gaps.filter((g) => g.term !== done && !handled.includes(g.term))
    setHandled((h) => [...h, done])
    setPending('')
    if (remaining[0]) push('assistant', say(ask(remaining[0])))
    else push('assistant', say("That's every skill the job asks for that I couldn't find. Add anything else you know to **My context** and every later resume will use it."))
  }

  const submit = async (raw: string) => {
    const text = raw.trim()
    if (!text || !current || busy) return
    setInput('')
    push('you', text)
    if (!pending && SKIP.test(text)) {
      push('assistant', say(`No problem, skipping **${current.term}**.`))
      moveOn(current.term)
      return
    }
    if (!pending && text.length < 12) {
      push('assistant', say(`Could you say a bit more? What did you do with **${current.term}**, and what came of it?`))
      return
    }
    const answer = pending ? `${pending}\n${text}` : text
    setBusy(true)
    try {
      const r = await acct.answerRun(runId, [{ term: current.term, text: answer }], acceptedOps)
      if (r.ops.length || r.projects.length) {
        onStored(r.evidence)
        onDrafted(r)
        setSnippets((s) => [...s, ...r.projects])
        const parts = [r.ops.length ? `${r.ops.length === 1 ? 'a bullet' : `${r.ops.length} bullets`} for your resume` : '', r.projects.length ? 'code for a new project to paste into Overleaf' : ''].filter(Boolean)
        push('assistant', say(`Thanks, I've written ${parts.join(' and ')} from that. It only uses what you said, so please check it below. I've also saved what you told me to My context.`))
        moveOn(current.term)
      } else if (r.followups.length) {
        setPending(answer)
        push('assistant', say(r.followups[0].question))
      } else {
        setPending(answer)
        const why = r.blocked[0]?.message
        push('assistant', say(why ? `I couldn't write that without adding something you didn't say: ${why} Tell me a little more, or say skip.` : `I couldn't write a bullet from that yet. Tell me a little more about what you did, or say skip.`))
      }
    } catch (e) {
      push('assistant', say(e instanceof Error ? e.message : 'Something went wrong. Try again.'))
    } finally {
      setBusy(false)
    }
  }

  if (!gaps.length && !inferred.length && !drafted.length && !snippets.length) return null
  return (
    <Card className="flex flex-col gap-space-md p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-2 font-headline-sm text-headline-sm text-on-surface">
            Fill the gaps
            <InfoTip align="left">
              The job asks for skills that aren't written anywhere in your resume or context. TailorTeX won't write something nobody told it, so it asks. If you've done any of these, say so in your own words. If you haven't, skip it: adding it wouldn't survive an interview.
            </InfoTip>
          </h2>
          <p className="mt-0.5 font-body-sm text-body-sm text-on-surface-variant">Answer in your own words. Your answers become part of your context.</p>
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

      {!hasModel && total > 0 && <Notice tone="warn">Add a model key in Settings first: writing from your answers needs one.</Notice>}

      {total > 0 && (
        <div className="flex max-h-[520px] flex-col gap-2.5 overflow-y-auto rounded-xl bg-surface-container-lowest p-1" aria-live="polite">
          {messages.map((m) => (
            <div key={m.id} className={`max-w-[92%] rounded-2xl px-3.5 py-2.5 font-body-md text-body-md leading-relaxed ${m.from === 'assistant' ? 'self-start rounded-tl-sm bg-surface-container-low text-on-surface' : 'self-end rounded-tr-sm bg-primary text-on-primary'}`}>
              {m.body}
            </div>
          ))}
          {busy && <div className="self-start rounded-2xl rounded-tl-sm bg-surface-container-low px-3.5 py-2.5 font-body-md text-body-md text-on-surface-variant"><Icon name="progress_activity" className="animate-spin text-[16px]" /> Writing…</div>}

          {snippets.map((sn) => (
            <ProjectSnippetCard key={sn.answer} snippet={sn} engine={engine} filename={filename} onDismiss={() => setSnippets((l) => l.filter((x) => x !== sn))} />
          ))}
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
              </div>
            </div>
          ))}
          <div ref={end} />
        </div>
      )}

      {current && (
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
            aria-label={`Your answer about ${current.term}`}
            placeholder={`About ${current.term}: what you built, what you used, what came of it…`}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" loading={busy} disabled={!input.trim() || !hasModel}><Icon name="send" className="text-[17px]" /> Send</Button>
            <Button type="button" variant="ghost" disabled={busy} onClick={() => void submit("I haven't done this")}>Skip {current.term}</Button>
            <span className="font-body-sm text-body-sm text-on-surface-variant">Enter to send, Shift+Enter for a new line</span>
          </div>
        </form>
      )}
    </Card>
  )
}
