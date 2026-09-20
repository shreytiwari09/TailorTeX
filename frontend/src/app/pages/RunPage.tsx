import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type Evidence, type Op } from '../../api'
import { base64ToBlob, downloadBlob, openInOverleaf, plain } from '../../util'
import { useAuth } from '../auth'
import { acct, type ChatResult, type SavedRun } from '../client'
import { atsOf, gainLabel } from '../format'
import { SkillChat, type Drafted } from '../run/SkillChat'
import { ChangeList, type Decision } from '../run/ChangeList'
import { Details } from '../run/Details'
import { Preview } from '../run/Preview'
import { ScoreHeader } from '../run/ScoreHeader'
import { Button, Card, Icon, Notice, Skeleton } from '../ui'

type View = { tex: string; pdf: string | null; after: SavedRun['after']; warnings: string[]; ats: number | null }

const opKey = (o: Op) => `${o.op}|${o.target}|${o.text ?? ''}`

/** Where a line was built up in steps, only the last version counts: each already contains the ones before. */
const latestOnly = (ops: Op[]) => {
  const last = new Map<string, Op>()
  for (const o of ops) if (o.op !== 'add') last.set(o.target, o)
  return ops.filter((o) => o.op === 'add' || last.get(o.target) === o)
}

const sign = (d: Record<number, Decision>) => JSON.stringify(Object.entries(d).filter(([, v]) => v.action !== 'kept').sort(([a], [b]) => Number(a) - Number(b)))

export function RunPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { profile } = useAuth()
  const [run, setRun] = useState<SavedRun | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [context, setContext] = useState<Evidence[]>([])
  const [decisions, setDecisions] = useState<Record<number, Decision>>({})
  const [built, setBuilt] = useState<Record<number, Decision>>({}) // the choices the preview currently reflects
  const [view, setView] = useState<View | null>(null)
  const [extra, setExtra] = useState<Op[]>([]) // bullets and skills drafted in the chat, then accepted
  const [extraGain, setExtraGain] = useState<Record<string, number>>({}) // what each of those is worth
  const [builtExtra, setBuiltExtra] = useState<Op[]>([]) // the ones the preview already includes
  const [drafted, setDrafted] = useState<Drafted[]>([])
  const [rebuilding, setRebuilding] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [serverKey, setServerKey] = useState(false) // a deployment can supply a model key of its own
  const feedbackSent = useRef<string | null>(null)

  useEffect(() => {
    let alive = true
    acct.run(id).then((r) => {
      if (!alive) return
      setRun(r)
      setView({ tex: r.tex, pdf: r.pdf, after: r.after, warnings: r.warnings, ats: r.ats?.after ?? null })
      // Reopening shows what the person chose last time, not every suggestion accepted again.
      if (r.accepted_ops) {
        const kept = new Set(r.accepted_ops.map((o) => `${o.op}|${o.target}`))
        const restored: Record<number, Decision> = {}
        for (const c of r.changes) if (!kept.has(`${c.op}|${c.target}`)) restored[c.id] = { action: 'reverted' }
        setDecisions(restored)
        setBuilt(restored)
        // Bullets the person added from their own answers come back among the accepted ops.
        const fromAnswers = r.accepted_ops.filter((o) => o.evidence.some((e) => /^ans\d+$/.test(e)))
        setExtra(fromAnswers)
        setBuiltExtra(fromAnswers)
      }
    }).catch((e: Error) => alive && setError(e.message))
    acct.context().then((c) => alive && setContext(c.entries)).catch(() => undefined)
    api.config().then((c) => alive && setServerKey(c.server_key)).catch(() => undefined)
    return () => {
      alive = false
    }
  }, [id])
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(t)
  }, [toast])

  const signature = sign(decisions)
  const dirty = signature !== sign(built) || extra.length !== builtExtra.length

  const pdfB64 = view?.pdf ?? null
  const pdfUrl = useMemo(() => (pdfB64 ? URL.createObjectURL(base64ToBlob(pdfB64, 'application/pdf')) : null), [pdfB64])
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl) }, [pdfUrl])

  const labels = useMemo(() => {
    const m: Record<string, { title: string; url?: string | null }> = { skills: { title: 'skills you confirmed' } }
    for (const e of context) m[e.id] = { title: e.source === 'github' && e.url ? e.url.replace(/^https?:\/\/github\.com\//, '') : e.title || e.text.slice(0, 40), url: e.url }
    return m
  }, [context])

  // The operations that make up the resume the person has chosen.
  const chosenOps = useCallback((): Op[] => {
    if (!run) return []
    const base = run.ops.flatMap((op, i) => {
      const d = decisions[i]
      if (d?.action === 'reverted') return []
      if (d?.action === 'edited') return [{ ...op, text: d.text ?? op.text, source: 'user' as const }]
      return [op]
    })
    // What the person added from the chat may replace a change already made to the same block, and where they
    // built a line up in steps, only the last version of it counts (each one already includes the earlier).
    const added = latestOnly(extra)
    const targets = new Set(added.filter((o) => o.op !== 'add').map((o) => o.target))
    return [...base.filter((o) => o.op === 'add' || !targets.has(o.target)), ...added]
  }, [run, decisions, extra])

  const sendFeedback = useCallback(() => {
    if (!run || !profile) return
    const sig = `${run.run_id}:${signature}`
    if (feedbackSent.current === sig) return
    feedbackSent.current = sig
    api.feedback({
      run_id: run.run_id, context: run.context, arm: run.arm, reward: run.reward, user: profile.id, key: null, provider: null, model: null,
      decisions: run.changes.map((c) => ({ change_id: c.id, action: decisions[c.id]?.action ?? 'kept', suggested: plain(c.after).slice(0, 2000), final: (decisions[c.id]?.text ?? '').slice(0, 2000) })),
    }).catch(() => undefined)
  }, [run, profile, signature, decisions])

  const apply = async () => {
    if (!run) return
    setRebuilding(true)
    try {
      const r = await acct.rebuildRun(run.saved_run_id, chosenOps(), true)
      setView({ tex: r.tex, pdf: r.pdf, after: r.after, warnings: r.warnings, ats: r.ats ?? null })
      setBuilt(decisions)
      setBuiltExtra(extra)
      sendFeedback()
      setToast('Your resume is updated.')
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Could not update your resume.')
    } finally {
      setRebuilding(false)
    }
  }

  // True opt-in for people who want it: leave everything out, then tick what to include.
  const reviewOneByOne = () => {
    if (run) setDecisions(Object.fromEntries(run.changes.map((c) => [c.id, { action: 'reverted' } as Decision])))
  }

  const onDrafted = (r: Pick<ChatResult, 'ops' | 'changes'>) => {
    const fresh = r.ops.map((op, i) => ({ op, change: r.changes[i] }))
    // A newer edit to a line (a Skills line, say) already contains the earlier one, so it replaces that card
    // instead of sitting beside it, where accepting both would apply two rewrites of the same line.
    const replaced = new Set(fresh.filter((f) => f.op.op !== 'add').map((f) => f.op.target))
    setDrafted((d) => [...d.filter((x) => x.op.op === 'add' || !replaced.has(x.op.target)), ...fresh])
  }
  const acceptDrafted = (d: Drafted) => {
    setExtra((x) => [...x, d.op])
    setExtraGain((g) => ({ ...g, [opKey(d.op)]: d.change.gain ?? 0 }))
    setDrafted((list) => list.filter((y) => y !== d))
  }

  const remove = async () => {
    if (!run || !window.confirm('Delete this tailored resume?')) return
    await acct.deleteRun(run.saved_run_id)
    navigate('/dashboard')
  }

  if (error) return <Notice tone="bad" className="mt-space-lg">{error} <Link to="/dashboard" className="font-semibold underline">Back to your resumes</Link></Notice>
  if (!run || !view) {
    return (
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <div className="flex flex-col gap-4 lg:col-span-7"><Skeleton className="h-24" /><Skeleton className="h-32" /><Skeleton className="h-64" /></div>
        <Skeleton className="h-[480px] lg:col-span-5" />
      </div>
    )
  }

  const filename = run.filename || 'resume'
  const score = atsOf({ ats: run.ats, before: run.before, after: view.after })
  const shownAfter = view.ats ?? score.after
  // Ticking or unticking moves an estimate with no round trip: the measured score, plus the worth of
  // every change now included minus those the preview already includes.
  const included = (d: Record<number, Decision>, cid: number) => (d[cid]?.action !== 'reverted' ? 1 : 0)
  const baseSwing = run.changes.reduce((n, c) => n + (included(decisions, c.id) - included(built, c.id)) * (c.gain ?? 0), 0)
  // What the chat added counts too: a skills line built up in steps is worth what its latest version is worth.
  const worthOf = (ops: Op[]) => latestOnly(ops).reduce((n, o) => n + (extraGain[opKey(o)] ?? 0), 0)
  const swing = baseSwing + worthOf(extra) - worthOf(builtExtra)
  const estimated = dirty && score.measured ? Math.max(0, Math.min(1, shownAfter + swing)) : null

  const must = run.keywords.filter((k) => k.must)
  const mustCovered = must.filter((k) => k.after !== 'missing').length
  const gaps = run.gains?.gaps ?? []
  const compileWarning = view.warnings.find((w) => w.includes("doesn't compile")) ?? null
  const otherWarnings = view.warnings.filter((w) => w !== compileWarning)

  return (
    <div className="grid grid-cols-1 gap-6 pb-24 lg:grid-cols-12">
      <div className="flex min-w-0 flex-col gap-space-lg lg:col-span-7">
        <Link to="/dashboard" className="inline-flex w-fit items-center gap-1 font-label-md text-label-md text-on-surface-variant hover:text-on-surface"><Icon name="arrow_back" className="text-[18px]" /> Resumes</Link>

        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="font-headline-md text-headline-md text-on-surface">{run.analysis.title || 'Tailored resume'}{run.analysis.company && <span className="text-on-surface-variant"> @ {run.analysis.company}</span>}</h1>
            <p className="mt-0.5 font-body-sm text-body-sm text-on-surface-variant">{run.usage.model}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {view.pdf && <Button size="sm" onClick={() => { downloadBlob(base64ToBlob(view.pdf!, 'application/pdf'), `${filename}.pdf`); sendFeedback() }}><Icon name="download" className="text-[17px]" /> PDF</Button>}
            <Button size="sm" variant="secondary" onClick={() => { downloadBlob(new Blob([view.tex], { type: 'application/x-tex' }), `${filename}.tex`); sendFeedback() }}>.tex</Button>
            <Button size="sm" variant="secondary" onClick={async () => { try { await navigator.clipboard.writeText(view.tex); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { setToast("Couldn't copy the LaTeX.") } sendFeedback() }}>{copied ? 'Copied' : 'Copy LaTeX'}</Button>
            <Button size="sm" variant="secondary" onClick={() => { openInOverleaf(view.tex, `${filename}.tex`, run.engine); sendFeedback() }}>Overleaf <Icon name="arrow_outward" className="text-[14px] text-outline" /></Button>
            <Button size="sm" variant="ghost" aria-label="Delete this resume" onClick={remove}><Icon name="delete" className="text-[18px]" /></Button>
          </div>
        </div>

        <ScoreHeader before={score.before} after={shownAfter} estimated={estimated} measured={score.measured} mustCovered={mustCovered} mustTotal={must.length} />

        <Summary run={run} shownAfter={shownAfter} before={score.before} compileWarning={compileWarning} gapGain={gaps.reduce((n, g) => n + g.gain, 0)} />

        {(otherWarnings.length > 0 || run.fit_note) && (
          <div className="flex flex-col gap-2">
            {run.fit_note && <Notice tone="accent">{run.fit_note}</Notice>}
            {otherWarnings.map((w, i) => <Notice key={i} tone="warn">{w}</Notice>)}
          </div>
        )}

        <ChangeList changes={run.changes} decisions={decisions} onDecide={(cid, d) => setDecisions((p) => ({ ...p, [cid]: d }))} labels={labels} onReviewOneByOne={reviewOneByOne} />

        <SkillChat
          runId={run.saved_run_id}
          gaps={gaps}
          inferred={run.inferred ?? []}
          acceptedOps={chosenOps()}
          drafted={drafted}
          hasModel={!!profile?.model.key_saved || serverKey}
          engine={run.engine}
          filename={filename}
          onDrafted={onDrafted}
          onAccept={acceptDrafted}
          onDiscard={(d) => setDrafted((list) => list.filter((y) => y !== d))}
          onStored={(items) => setContext((c) => [...c, ...items.filter((i) => !c.some((x) => x.id === i.id))])}
        />

        <Details run={run} after={view.after} before={run.before} />
      </div>

      <aside className="lg:col-span-5">
        <div className="lg:sticky lg:top-[88px]">
          <Preview pdfUrl={pdfUrl} tex={view.tex} busy={rebuilding} compileError={compileWarning} />
        </div>
      </aside>

      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-outline-variant/50 bg-surface-container-lowest/95 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-3 px-gutter-mobile py-3 md:px-gutter">
          <div className="flex items-center gap-2.5 font-body-sm text-body-sm text-on-surface-variant">
            <span className={`h-2 w-2 shrink-0 rounded-full ${dirty ? 'bg-amber-500' : 'bg-emerald-500'}`} />
            {dirty
              ? <span>You changed what goes in your resume{swing !== 0 && score.measured ? ` (${gainLabel(swing)} ATS)` : ''}. Apply to update the preview.</span>
              : <span>Your resume matches the changes ticked above.</span>}
          </div>
          <div className="flex items-center gap-2">
            {dirty && <Button size="sm" variant="ghost" onClick={() => { setDecisions(built); setExtra(builtExtra) }}>Undo</Button>}
            {dirty
              ? <Button size="sm" loading={rebuilding} onClick={() => void apply()}><Icon name="check" className="text-[17px]" /> Apply my choices</Button>
              : view.pdf
                ? <Button size="sm" onClick={() => { downloadBlob(base64ToBlob(view.pdf!, 'application/pdf'), `${filename}.pdf`); sendFeedback() }}><Icon name="download" className="text-[17px]" /> Download PDF</Button>
                : <Button size="sm" onClick={() => { openInOverleaf(view.tex, `${filename}.tex`, run.engine); sendFeedback() }}>Open in Overleaf <Icon name="arrow_outward" className="text-[14px]" /></Button>}
          </div>
        </div>
      </div>
      {toast && <div role="status" className="fixed bottom-20 left-1/2 z-50 max-w-[calc(100vw-2rem)] -translate-x-1/2 rounded-lg bg-inverse-surface px-4 py-2.5 font-body-sm text-body-sm text-inverse-on-surface shadow-xl">{toast}</div>}
    </div>
  )
}

/** What happened, in a few plain sentences, and what to do next. */
function Summary({ run, shownAfter, before, compileWarning, gapGain }: { run: SavedRun; shownAfter: number; before: number; compileWarning: string | null; gapGain: number }) {
  const n = (op: string) => run.changes.filter((c) => c.op === op).length
  const did: string[] = []
  const add = (count: number, one: string, many: string) => { if (count) did.push(`${count} ${count === 1 ? one : many}`) }
  add(n('rewrite'), 'bullet reworded', 'bullets reworded')
  add(n('add'), 'bullet added', 'bullets added')
  add(n('drop') + n('drop_entry'), 'bullet removed', 'bullets removed')
  add(n('reorder') + n('reorder_entries'), 'list reordered', 'lists reordered')
  const sentence = did.length ? did.join(', ').replace(/, ([^,]*)$/, ' and $1') : 'No edits were needed'
  const delta = Math.round((shownAfter - before) * 100)
  const unproven = run.keywords.filter((k) => k.must && k.after === 'missing' && k.evidence_ids.length === 0)

  return (
    <Card className="flex flex-col gap-2 p-5">
      <p className="font-body-lg text-body-lg leading-relaxed text-on-surface">
        {sentence}, each checked against your resume and context.{' '}
        {delta > 0 ? <>That moved your ATS score from <strong>{Math.round(before * 100)}%</strong> to <strong>{Math.round(shownAfter * 100)}%</strong>.</> : <>Your ATS score is <strong>{Math.round(shownAfter * 100)}%</strong>.</>}
      </p>
      {unproven.length > 0 && (
        <p className="font-body-md text-body-md leading-relaxed text-on-surface-variant">
          {unproven.length} required {unproven.length === 1 ? 'skill' : 'skills'} ({unproven.map((k) => k.term).join(', ')}) {unproven.length === 1 ? "isn't" : "aren't"} anywhere in your resume or context, so {unproven.length === 1 ? 'it was' : 'they were'} left out.
          {gapGain > 0 && <> If you've done {unproven.length === 1 ? 'that' : 'any of those'}, tell us below: backing them could add up to <strong className="text-on-surface">{gainLabel(gapGain)}</strong>.</>}
        </p>
      )}
      {compileWarning && (
        <div className="mt-1 flex items-start gap-2 rounded-lg bg-amber-50 px-3.5 py-2.5 font-body-sm text-body-sm text-amber-900">
          <Icon name="warning" className="mt-0.5 text-[18px]" />
          <span>Your own resume doesn't compile, so there is no PDF and no readability check. {compileWarning}</span>
        </div>
      )}
    </Card>
  )
}
