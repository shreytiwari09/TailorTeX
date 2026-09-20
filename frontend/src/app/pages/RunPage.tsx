import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type Change, type Evidence, type Keyword, type Op, type Recommendation, type TermStatus } from '../../api'
import { base64ToBlob, downloadBlob, openInOverleaf, plain, wordDiff } from '../../util'
import { useAuth } from '../auth'
import { acct, type SavedRun } from '../client'
import { pct } from '../format'
import { Badge, Button, Card, Icon, InfoTip, Notice, Skeleton, TextArea } from '../ui'

type Decision = { action: 'kept' | 'reverted' | 'edited'; text?: string }
type Tab = 'changes' | 'recommendations' | 'keywords' | 'guardrails' | 'files'

export function RunPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { profile } = useAuth()
  const [run, setRun] = useState<SavedRun | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [context, setContext] = useState<Evidence[]>([])
  const [skills, setSkills] = useState<string[]>([])
  const [tab, setTab] = useState<Tab>('changes')
  const [decisions, setDecisions] = useState<Record<number, Decision>>({})
  const [built, setBuilt] = useState('[]')
  const [view, setView] = useState<{ tex: string; pdf: string | null; after: SavedRun['after']; warnings: string[] } | null>(null)
  const [rebuilding, setRebuilding] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const feedbackSent = useRef<string | null>(null)

  useEffect(() => {
    let alive = true
    acct.run(id).then((r) => {
      if (!alive) return
      setRun(r)
      setView({ tex: r.tex, pdf: r.pdf, after: r.after, warnings: r.warnings })
    }).catch((e: Error) => alive && setError(e.message))
    acct.context().then((c) => { if (alive) { setContext(c.entries); setSkills(c.skills) } }).catch(() => undefined)
    return () => {
      alive = false
    }
  }, [id])
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(t)
  }, [toast])

  const signature = JSON.stringify(Object.entries(decisions).filter(([, v]) => v.action !== 'kept').sort(([a], [b]) => Number(a) - Number(b)))
  const dirty = signature !== built
  const pdfB64 = view?.pdf ?? null
  const pdfUrl = useMemo(() => (pdfB64 ? URL.createObjectURL(base64ToBlob(pdfB64, 'application/pdf')) : null), [pdfB64])
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl) }, [pdfUrl])

  const labels = useMemo(() => {
    const m: Record<string, { title: string; url?: string | null }> = { skills: { title: 'skills you confirmed' } }
    for (const e of context) m[e.id] = { title: e.source === 'github' && e.url ? e.url.replace(/^https?:\/\/github\.com\//, '') : e.title || e.text.slice(0, 40), url: e.url }
    return m
  }, [context])

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

  const rebuild = async () => {
    if (!run) return
    setRebuilding(true)
    try {
      const ops: Op[] = run.ops.flatMap((op, i) => {
        const d = decisions[i]
        if (d?.action === 'reverted') return []
        if (d?.action === 'edited') return [{ ...op, text: d.text ?? op.text, source: 'user' as const }]
        return [op]
      })
      const r = await acct.rebuildRun(run.saved_run_id, ops, true)
      setView({ tex: r.tex, pdf: r.pdf, after: r.after, warnings: r.warnings })
      setBuilt(signature)
      sendFeedback()
      setToast('Rebuilt with your choices.')
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Could not rebuild.')
    } finally {
      setRebuilding(false)
    }
  }

  const confirmSkill = async (term: string) => {
    if (skills.some((s) => s.toLowerCase() === term.toLowerCase())) return
    const next = [...skills, term]
    setSkills(next)
    await acct.saveSkills(next).catch(() => undefined)
    setToast(`Added “${term}” to the skills you can defend. Tailor again to use it.`)
  }
  const remove = async () => {
    if (!run || !window.confirm('Delete this tailored resume?')) return
    await acct.deleteRun(run.saved_run_id)
    navigate('/dashboard')
  }

  if (error) return <Notice tone="bad" className="mt-space-lg">{error} <Link to="/dashboard" className="font-semibold underline">Back to your resumes</Link></Notice>
  if (!run || !view) {
    return (
      <div className="flex flex-col gap-space-md">
        <Skeleton className="h-24" />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-32" />)}</div>
        <Skeleton className="h-64" />
      </div>
    )
  }

  const filename = run.filename || 'resume'
  const kept = run.changes.filter((c) => decisions[c.id]?.action !== 'reverted').length
  const recs = run.recommendations ?? []
  const must = run.keywords.filter((k) => k.must)
  const nice = run.keywords.filter((k) => !k.must)
  const present = (list: Keyword[]) => list.filter((k) => k.after !== 'missing').length
  const after = view.after
  const passing = after.checks.filter((c) => c.ok).length
  const compileWarning = view.warnings.find((w) => w.includes("doesn't compile")) ?? null
  const otherWarnings = view.warnings.filter((w) => w !== compileWarning)

  return (
    <div className="flex flex-col gap-space-lg pb-24">
      <Link to="/dashboard" className="inline-flex w-fit items-center gap-1 font-label-md text-label-md text-on-surface-variant hover:text-on-surface"><Icon name="arrow_back" className="text-[18px]" /> Resumes</Link>

      <Card className="flex flex-col justify-between gap-4 p-5 lg:flex-row lg:items-center">
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2.5">
            <Badge tone="accent" className="rounded font-code-sm uppercase tracking-wider">Tailored</Badge>
            <h1 className="font-headline-sm text-headline-sm text-on-surface">{run.analysis.title || 'Tailored resume'}</h1>
            {run.analysis.company && <span className="whitespace-nowrap font-headline-sm text-headline-sm text-on-surface"><span className="mr-1.5 text-on-surface-variant">@</span>{run.analysis.company}</span>}
          </div>
          <div className="flex flex-wrap items-center gap-3 font-body-sm text-body-sm text-on-surface-variant">
            <span className="flex items-center gap-1.5 font-medium text-emerald-700"><span className="h-2 w-2 rounded-full bg-emerald-500" /> {run.changes.length} changes</span>
            <span className="text-outline-variant">·</span>
            <span className={`flex items-center gap-1.5 font-medium ${run.blocked.length ? 'text-error' : ''}`}><span className={`h-2 w-2 rounded-full ${run.blocked.length ? 'bg-error' : 'bg-outline-variant'}`} /> {run.blocked.length} blocked by guardrails</span>
            <span className="text-outline-variant">·</span>
            <span className="font-code-sm text-code-sm">{run.engine} · {run.usage.model}</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {view.pdf && <Button size="sm" onClick={() => { downloadBlob(base64ToBlob(view.pdf!, 'application/pdf'), `${filename}.pdf`); sendFeedback() }}><Icon name="download" className="text-[17px]" /> Download PDF</Button>}
          <Button size="sm" variant="secondary" onClick={() => { downloadBlob(new Blob([view.tex], { type: 'application/x-tex' }), `${filename}.tex`); sendFeedback() }}><Icon name="description" className="text-[17px] text-on-surface-variant" /> .tex</Button>
          <Button size="sm" variant="secondary" onClick={async () => { try { await navigator.clipboard.writeText(view.tex); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { setToast("Couldn't copy. Use the PDF & LaTeX tab.") } sendFeedback() }}><Icon name={copied ? 'check' : 'content_copy'} className="text-[17px] text-on-surface-variant" /> {copied ? 'Copied' : 'Copy LaTeX'}</Button>
          <Button size="sm" variant="secondary" onClick={() => { openInOverleaf(view.tex, `${filename}.tex`, run.engine); sendFeedback() }}>Open in Overleaf <Icon name="arrow_outward" className="text-[14px] text-outline" /></Button>
          <Button size="sm" variant="ghost" aria-label="Delete this resume" onClick={remove}><Icon name="delete" className="text-[18px]" /></Button>
        </div>
      </Card>

      <Summary run={run} view={view} recs={recs} onTab={setTab} compileWarning={compileWarning} />

      {/* Whatever the summary already explained isn't repeated here. */}
      {(otherWarnings.length > 0 || run.fit_note) && (
        <div className="flex flex-col gap-2">
          {run.fit_note && <Notice tone="accent">{run.fit_note}</Notice>}
          {otherWarnings.map((w, i) => <Notice key={i} tone="warn">{w}</Notice>)}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Score label="Must-have ATS" info="Share of the job's essential keywords found in your resume. In bullets counts fully; only in the Skills list counts 60%." before={run.before.must_have} after={after.must_have} left={`${present(must)}/${must.length} present`} />
        <Score label="Nice-to-have ATS" info="The same, for the job's preferred extras." before={run.before.nice_to_have} after={after.nice_to_have} left={`${present(nice)}/${nice.length} present`} accent />
        <Score label="Title alignment" info="How closely the job titles on your resume match the one in the posting, ignoring words like Senior. TailorTeX never rewrites a job title, so this only moves if you change it yourself." before={run.before.title} after={after.title} left={after.title >= 1 ? 'Exact match' : after.title >= 0.5 ? 'Close' : 'No title matches'} />
        <Score label="ATS parse health" info="Checks on the PDF's extracted text: readable text, no broken ligatures, contact details found, standard headings, single-column order. Needs a PDF, so it's empty when your resume doesn't compile." before={run.before.health} after={after.health} left={after.checks.length ? `${passing} of ${after.checks.length} checks pass` : 'needs a PDF'} grade />
        <PagesTile after={after} limit={run.page_limit} />
      </div>

      <Card className="flex items-center justify-between overflow-x-auto p-1.5">
        <div role="tablist" className="flex shrink-0 items-center gap-1">
          <TabBtn id="changes" tab={tab} setTab={setTab} icon="difference" label="Changes" count={run.changes.length} />
          <TabBtn id="recommendations" tab={tab} setTab={setTab} icon="verified" label="ATS recommendations" count={recs.length} />
          <TabBtn id="keywords" tab={tab} setTab={setTab} icon="tag" label="Keyword matrix" />
          <TabBtn id="guardrails" tab={tab} setTab={setTab} icon="security" label="Guardrails" count={run.blocked.length + run.left_out.length} bad={run.blocked.length > 0} />
          <TabBtn id="files" tab={tab} setTab={setTab} icon="splitscreen" label="PDF & LaTeX" />
        </div>
      </Card>

      {tab === 'changes' && (
        <div className="flex flex-col gap-4">
          {run.changes.length === 0 && <Card className="p-6 text-center font-body-md text-body-md text-on-surface-variant">No changes were needed, or none passed the guardrails.</Card>}
          {run.changes.map((c) => <ChangeCard key={c.id} change={c} decision={decisions[c.id] ?? { action: 'kept' }} onDecide={(d) => setDecisions((p) => ({ ...p, [c.id]: d }))} labels={labels} />)}
        </div>
      )}
      {tab === 'recommendations' && <Recommendations recs={recs} skills={skills} labels={labels} onConfirm={confirmSkill} onAgain={() => navigate('/new', { state: { jd: run.jd, candidates: 3 } })} />}
      {tab === 'keywords' && <KeywordMatrix must={must} nice={nice} mustPct={after.must_have} nicePct={after.nice_to_have} skills={skills} labels={labels} onConfirm={confirmSkill} />}
      {tab === 'guardrails' && <Guardrails run={run} skills={skills} onConfirm={confirmSkill} />}
      {tab === 'files' && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card className="overflow-hidden p-2">{pdfUrl ? <iframe title="Tailored resume PDF" src={pdfUrl} className="h-[min(1000px,80vh)] w-full rounded-lg bg-white" /> : <div className="p-6 text-center font-body-md text-body-md text-on-surface-variant">No PDF for this run. Open the .tex in Overleaf to compile it.</div>}</Card>
          <Card className="overflow-hidden"><pre className="max-h-[min(1000px,80vh)] overflow-auto whitespace-pre-wrap break-words bg-surface-container-low p-4 font-code-sm text-code-sm text-on-surface"><code>{view.tex}</code></pre></Card>
        </div>
      )}

      <div className="fixed inset-x-0 bottom-0 z-40 border-t border-outline-variant/50 bg-surface-container-lowest/95 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-3 px-gutter-mobile py-3 md:px-gutter">
          <div className="flex items-center gap-2.5 font-body-sm text-body-sm text-on-surface-variant">
            <span className={`h-2 w-2 shrink-0 rounded-full ${dirty ? 'bg-amber-500' : 'bg-emerald-500'}`} />
            <span>
              {dirty
                ? `${kept} of ${run.changes.length} changes in your resume — rebuild to apply`
                : `All ${run.changes.length} changes are in your resume. Remove any you don't want.`}
            </span>
            {!dirty && view.after.pages !== null && <span className="hidden sm:inline">· {view.after.pages} page{view.after.pages === 1 ? '' : 's'}</span>}
          </div>
          <div className="flex items-center gap-2">
            {dirty && <Button size="sm" variant="ghost" onClick={() => setDecisions({})}>Undo my changes</Button>}
            {dirty
              ? <Button size="sm" loading={rebuilding} onClick={rebuild}><Icon name="build" className="text-[17px]" /> Rebuild with my choices</Button>
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

/** The whole run in plain words: what it did to the resume, whether that helped, and the one thing to do next. */
function Summary({ run, view, recs, onTab, compileWarning }: { run: SavedRun; view: { after: SavedRun['after']; pdf: string | null }; recs: Recommendation[]; onTab: (t: Tab) => void; compileWarning: string | null }) {
  const n = (op: Change['op']) => run.changes.filter((c) => c.op === op).length
  const did: string[] = []
  const add = (count: number, one: string, many: string) => count && did.push(`${count} ${count === 1 ? one : many}`)
  add(n('rewrite'), 'bullet rewritten', 'bullets rewritten')
  add(n('add'), 'bullet added', 'bullets added')
  add(n('drop') + n('drop_entry'), 'bullet removed', 'bullets removed')
  add(n('reorder') + n('reorder_entries'), 'list reordered', 'lists reordered')
  const sentence = did.length ? did.join(', ').replace(/, ([^,]*)$/, ' and $1') : 'No edits were applied'

  const before = run.before.must_have
  const after = view.after.must_have
  const delta = Math.round((after - before) * 100)
  const compiled = view.after.pages !== null
  const high = recs.filter((r) => r.priority === 'high').length

  const next = !compiled
    ? { text: `${compileWarning ?? "Your resume didn't compile, so there's no PDF."} Fix it in your LaTeX editor and tailor again; the tailored .tex below has the same problem.`, tab: null, label: null }
    : high
      ? { text: `${high} high-priority ${high === 1 ? 'item' : 'items'} could raise your match further.`, tab: 'recommendations' as Tab, label: 'See recommendations' }
      : { text: 'Read each change below, remove any you would not say in an interview, then download the PDF.', tab: null, label: null }

  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-center gap-2">
        <Icon name="summarize" className="text-[20px] text-primary" />
        <h2 className="font-headline-sm text-headline-sm text-on-surface">What TailorTeX did</h2>
      </div>
      <p className="font-body-lg text-body-lg leading-relaxed text-on-surface">
        {sentence} in your resume, each one checked against your resume and your context.{' '}
        {delta > 0
          ? <>That took the job's must-have keywords from <strong>{pct(before)}</strong> to <strong>{pct(after)}</strong> of the list.</>
          : delta < 0
            ? <>Must-have keyword coverage moved from {pct(before)} to {pct(after)}.</>
            : <>Must-have keyword coverage stayed at <strong>{pct(after)}</strong>.</>}
        {run.blocked.length > 0 && <> {run.blocked.length} further {run.blocked.length === 1 ? 'edit was' : 'edits were'} refused because nothing you have backs {run.blocked.length === 1 ? 'it' : 'them'}.</>}
      </p>
      <div className="flex flex-wrap items-center gap-2 rounded-lg bg-surface-container-low px-3.5 py-2.5">
        <Icon name={compiled ? 'arrow_forward' : 'warning'} className={`text-[18px] ${compiled ? 'text-primary' : 'text-amber-600'}`} />
        <span className="font-body-md text-body-md text-on-surface">{next.text}</span>
        {next.tab && <button type="button" onClick={() => onTab(next.tab as Tab)} className="font-label-md text-label-md font-semibold text-primary hover:underline">{next.label}</button>}
      </div>
    </Card>
  )
}

// --- score tiles -----------------------------------------------------------------------------------------------

function Score({ label, info, before, after, left, accent, grade }: { label: string; info: string; before: number | null; after: number | null; left: string; accent?: boolean; grade?: boolean }) {
  const a = after ?? 0
  const b = before ?? a
  const delta = Math.round((a - b) * 100)
  const gain = Math.max(0, a - b)
  const loss = Math.max(0, b - a)
  const letter = a >= 0.95 ? 'A' : a >= 0.8 ? 'B' : 'C'
  return (
    <Card className="flex flex-col justify-between p-4 transition-all hover:border-outline-variant">
      <div>
        <div className="flex items-center justify-between">
          <span className="font-code-sm text-code-sm font-semibold uppercase tracking-wider text-on-surface-variant">{label}</span>
          <InfoTip align="right">{info}</InfoTip>
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span className={`font-mono text-[26px] font-bold leading-none tracking-tight ${grade && a >= 0.95 ? 'text-emerald-700' : 'text-on-surface'}`}>{pct(after)}</span>
          {grade && after !== null ? <Badge className="rounded font-code-sm">{letter}-grade</Badge> : delta !== 0 && <span className={`rounded border px-1.5 py-0.5 font-code-sm text-[11px] font-semibold ${delta > 0 ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-red-200 bg-error-container text-on-error-container'}`}>{delta > 0 ? '+' : ''}{delta}%</span>}
        </div>
      </div>
      <div className="mt-4">
        <div className="flex h-2 w-full overflow-hidden rounded-full bg-surface-variant">
          <div className="h-full bg-outline" style={{ width: `${Math.min(a, b) * 100}%` }} />
          {gain > 0 && <div className={`h-full ${accent ? 'bg-primary' : 'bg-emerald-500'}`} style={{ width: `${gain * 100}%` }} />}
          {loss > 0 && <div className="h-full bg-error/60" style={{ width: `${loss * 100}%` }} />}
        </div>
        <div className="mt-2 flex items-center justify-between font-code-sm text-[11px] text-on-surface-variant">
          <span className="truncate">{grade ? left : `${pct(before)} → ${pct(after)}`}</span>
          {!grade && <span className="truncate pl-2 font-medium">{left}</span>}
        </div>
      </div>
    </Card>
  )
}

function PagesTile({ after, limit }: { after: SavedRun['after']; limit: number }) {
  const pages = after.pages
  const fill = after.page_fill
  const over = pages !== null && pages > limit
  return (
    <Card className="flex flex-col justify-between p-4">
      <div>
        <div className="flex items-center justify-between">
          <span className="font-code-sm text-code-sm font-semibold uppercase tracking-wider text-on-surface-variant">Pages</span>
          <InfoTip align="right">Length of the compiled resume and how full the last page is. Empty when your resume doesn't compile.</InfoTip>
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <span className="font-mono text-[26px] font-bold leading-none tracking-tight text-on-surface">{pages ?? '–'}</span>
          <span className="font-body-sm text-body-sm font-medium text-on-surface-variant">/ {limit} {limit === 1 ? 'page' : 'pages'}</span>
        </div>
      </div>
      <div className="mt-4">
        <div className="h-2 w-full overflow-hidden rounded-full bg-surface-variant"><div className={`h-full ${over ? 'bg-error' : 'bg-primary'}`} style={{ width: `${(fill ?? 0) * 100}%` }} /></div>
        <div className="mt-2 flex items-center justify-between font-code-sm text-[11px] text-on-surface-variant">
          <span>{fill !== null ? `${pct(fill)} filled` : 'needs a PDF'}</span>
          <span className={`font-medium ${over ? 'text-error' : 'text-emerald-700'}`}>{pages === null ? '' : over ? 'Over the limit' : 'Within the limit'}</span>
        </div>
      </div>
    </Card>
  )
}

function TabBtn({ id, tab, setTab, icon, label, count, bad }: { id: Tab; tab: Tab; setTab: (t: Tab) => void; icon: string; label: string; count?: number; bad?: boolean }) {
  const on = tab === id
  return (
    <button type="button" role="tab" aria-selected={on} onClick={() => setTab(id)} className={`flex items-center gap-2 whitespace-nowrap rounded-lg border px-3.5 py-2 font-label-md text-label-md transition-all ${on ? 'border-primary-fixed bg-primary-fixed/40 font-semibold text-primary' : 'border-transparent text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface'}`}>
      <Icon name={icon} className="text-[16px]" /> {label}
      {count !== undefined && <span className={`rounded-full px-1.5 font-code-sm text-[11px] font-semibold ${on ? 'bg-primary text-on-primary' : bad ? 'bg-error-container text-on-error-container' : 'bg-surface-container text-on-surface-variant'}`}>{count}</span>}
    </button>
  )
}

// --- changes -----------------------------------------------------------------------------------------------------

const OP: Record<Change['op'], { label: string; cls: string }> = {
  rewrite: { label: 'Rewritten', cls: 'border-primary-fixed bg-primary-fixed/40 text-primary' },
  add: { label: 'Added bullet', cls: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
  drop: { label: 'Removed', cls: 'border-red-200 bg-error-container text-on-error-container' },
  drop_entry: { label: 'Removed', cls: 'border-red-200 bg-error-container text-on-error-container' },
  reorder: { label: 'Reordered', cls: 'border-outline-variant bg-surface-container text-on-surface-variant' },
  reorder_entries: { label: 'Reordered', cls: 'border-outline-variant bg-surface-container text-on-surface-variant' },
}

function ChangeCard({ change, decision, onDecide, labels }: { change: Change; decision: Decision; onDecide: (d: Decision) => void; labels: Record<string, { title: string; url?: string | null }> }) {
  const [editing, setEditing] = useState(false)
  const current = decision.action === 'edited' ? decision.text ?? change.after : change.after
  const [draft, setDraft] = useState(plain(current))
  const editable = change.op === 'rewrite' || change.op === 'add'
  const reverted = decision.action === 'reverted'
  const op = OP[change.op]
  const where = [change.section, change.heading].filter(Boolean).join(' › ')
  const short = (t: string) => (plain(t).length > 90 ? `${plain(t).slice(0, 88)}…` : plain(t))
  return (
    <Card className={`flex flex-col gap-3 p-5 transition-all hover:border-outline-variant ${reverted ? 'opacity-60' : ''}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className={`rounded border px-2 py-0.5 font-code-sm text-[11px] font-semibold uppercase tracking-wider ${op.cls}`}>{op.label}</span>
          {change.source === 'fit' && <Badge tone="warn">page fit</Badge>}
          {decision.action === 'edited' && <Badge tone="accent">your edit</Badge>}
          <span className="text-outline-variant">/</span>
          <span className="truncate font-code-sm text-code-sm font-medium text-on-surface-variant">{where}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={`flex items-center gap-1 rounded border px-2 py-0.5 font-code-sm text-[11px] font-semibold uppercase tracking-wider ${reverted ? 'border-outline-variant bg-surface-container text-on-surface-variant' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
            <Icon name={reverted ? 'block' : 'check'} className="text-[13px]" /> {reverted ? 'Not used' : 'In your resume'}
          </span>
          <Pill tone={reverted ? 'good' : 'bad'} icon={reverted ? 'undo' : 'close'} label={reverted ? 'Put it back' : 'Remove'} onClick={() => onDecide(reverted ? { action: 'kept' } : { action: 'reverted' })} />
          {editable && !reverted && <Pill tone="accent" icon="edit" label={decision.action === 'edited' ? 'Edit again' : 'Edit'} onClick={() => { setDraft(plain(current)); setEditing(true) }} />}
        </div>
      </div>
      {editing ? (
        <div className="flex flex-col gap-2">
          <TextArea rows={3} value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Your version" />
          <div className="flex items-center gap-2">
            <Button size="sm" disabled={!draft.trim()} onClick={() => { onDecide({ action: 'edited', text: draft.trim() }); setEditing(false) }}>Save my version</Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
            <span className="font-body-sm text-body-sm text-on-surface-variant">Your own words aren't checked against your context: you're vouching for them.</span>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-outline-variant/40 bg-surface-container-low p-3.5 font-body-md text-body-md leading-relaxed text-on-surface">
          {change.op === 'rewrite' && wordDiff(plain(change.before), plain(current)).map((p, i) => (
            <span key={i} className={p.kind === 'del' ? 'rounded border border-red-200 bg-error-container px-1 text-on-error-container line-through' : p.kind === 'ins' ? 'rounded border border-emerald-200 bg-emerald-50 px-1 font-medium text-emerald-900' : ''}>{p.text}</span>
          ))}
          {change.op === 'add' && <span className="rounded border border-emerald-200 bg-emerald-50 px-1 font-medium text-emerald-900">+ {plain(current)}</span>}
          {(change.op === 'drop' || change.op === 'drop_entry') && <span className="rounded border border-red-200 bg-error-container px-1 text-on-error-container line-through">{plain(change.before)}</span>}
          {(change.op === 'reorder' || change.op === 'reorder_entries') && change.before_list && change.after_list && (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <ol className="list-decimal pl-5 text-on-surface-variant">{change.before_list.map((t, i) => <li key={i}>{short(t)}</li>)}</ol>
              <ol className="list-decimal pl-5">{change.after_list.map((t, i) => <li key={i} className={change.before_list?.[i] !== t ? 'font-medium text-primary' : ''}>{short(t)}</li>)}</ol>
            </div>
          )}
        </div>
      )}
      {(change.reason || change.evidence.length > 0) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-outline-variant/30 pt-2">
          <div className="flex flex-wrap items-center gap-2">
            {change.evidence.length > 0 && <span className="font-code-sm text-[11px] font-medium uppercase tracking-wider text-on-surface-variant">Backed by</span>}
            {change.evidence.map((eid) => {
              const l = labels[eid]
              const chip = <span className="inline-flex items-center gap-1 rounded border border-outline-variant/40 bg-surface-container px-2 py-0.5 font-code-sm text-[11px] text-primary"><Icon name="verified_user" className="text-[13px] text-emerald-600" />{l?.title ?? eid}</span>
              return l?.url ? <a key={eid} href={l.url} target="_blank" rel="noreferrer" className="hover:underline">{chip}</a> : <span key={eid}>{chip}</span>
            })}
          </div>
          {change.reason && <span className="font-body-sm text-body-sm italic text-on-surface-variant">{change.reason}</span>}
        </div>
      )}
    </Card>
  )
}

/** An action, not a state: pressing it always changes something. */
function Pill({ tone, icon, label, onClick }: { tone: 'good' | 'bad' | 'accent'; icon: string; label: string; onClick: () => void }) {
  const hover = { good: 'hover:border-emerald-200 hover:bg-emerald-50 hover:text-emerald-700', bad: 'hover:border-red-200 hover:bg-error-container hover:text-on-error-container', accent: 'hover:border-primary-fixed hover:bg-primary-fixed/40 hover:text-primary' }[tone]
  return (
    <button type="button" onClick={onClick} className={`flex items-center gap-1 rounded border border-outline-variant bg-surface-container-lowest px-2.5 py-1 font-label-md text-[12px] text-on-surface-variant transition-all ${hover}`}>
      <Icon name={icon} className="text-[14px]" /> {label}
    </button>
  )
}

// --- recommendations, keywords, guardrails ----------------------------------------------------------------------------

const PRIORITY = {
  high: { label: 'High priority', cls: 'border-red-200 bg-error-container text-on-error-container' },
  medium: { label: 'Medium priority', cls: 'border-amber-200 bg-amber-50 text-amber-800' },
  low: { label: 'Low priority', cls: 'border-primary-fixed bg-primary-fixed/40 text-primary' },
} as const

function Recommendations({ recs, skills, labels, onConfirm, onAgain }: { recs: Recommendation[]; skills: string[]; labels: Record<string, { title: string }>; onConfirm: (t: string) => void; onAgain: () => void }) {
  if (!recs.length) return <Card className="p-6 text-center font-body-md text-body-md text-on-surface-variant">Nothing to fix: this version covers what it can prove.</Card>
  return (
    <Card className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="font-headline-sm text-headline-sm text-on-surface">Prioritized action items</h3>
          <p className="mt-0.5 font-body-sm text-body-sm text-on-surface-variant">Built from what was measured on your PDF's text and what your context can back.</p>
        </div>
        <Badge tone="accent" className="rounded font-code-sm">{recs.length} {recs.length === 1 ? 'item' : 'items'}</Badge>
      </div>
      <div className="flex flex-col gap-3">
        {recs.map((r, i) => {
          const p = PRIORITY[r.priority]
          const confirmed = !!r.term && skills.some((s) => s.toLowerCase() === r.term!.toLowerCase())
          return (
            <div key={i} className="flex flex-col justify-between gap-4 rounded-xl border border-outline-variant/40 bg-surface-container-low p-4 transition-all hover:border-outline-variant md:flex-row md:items-center">
              <div className="flex items-start gap-3">
                <span className={`mt-0.5 shrink-0 rounded border px-2 py-0.5 font-code-sm text-[10px] font-semibold uppercase ${p.cls}`}>{p.label}</span>
                <div className="flex flex-col">
                  <span className="font-label-md text-label-md font-semibold text-on-surface">{r.title}</span>
                  <span className="mt-0.5 font-body-sm text-body-sm text-on-surface-variant">{r.detail}{r.evidence.length > 0 && r.action === 'use_context' && !r.detail.includes('Backed by') ? ` (${r.evidence.map((e) => labels[e]?.title ?? e).join(', ')})` : ''}</span>
                </div>
              </div>
              {r.action === 'confirm_skill' && r.term && <Button size="sm" variant="secondary" disabled={confirmed} onClick={() => onConfirm(r.term!)}>{confirmed ? 'Confirmed' : 'I have this'}</Button>}
              {r.action === 'use_context' && <Button size="sm" onClick={onAgain}>Tailor again (best of 3)</Button>}
              {r.action === 'fix_source' && <Link to="/settings" className="inline-flex shrink-0 items-center justify-center rounded-full border border-outline-variant bg-surface-container-lowest px-4 py-2 font-label-md text-label-md font-semibold text-on-surface hover:bg-surface-container-low">Edit resume</Link>}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

const KW: Record<TermStatus, { cls: string; icon: string; tip: string }> = {
  context: { cls: 'border-emerald-200 bg-emerald-50 text-emerald-700', icon: 'check', tip: 'Used in a bullet' },
  listed: { cls: 'border-amber-200 bg-amber-50 text-amber-800', icon: 'remove', tip: 'Only in the Skills list' },
  missing: { cls: 'border-red-200 bg-error-container text-on-error-container', icon: 'close', tip: 'Not found' },
}

function KeywordMatrix({ must, nice, mustPct, nicePct, skills, labels, onConfirm }: { must: Keyword[]; nice: Keyword[]; mustPct: number; nicePct: number; skills: string[]; labels: Record<string, { title: string }>; onConfirm: (t: string) => void }) {
  const list = (title: string, dot: string, items: Keyword[], p: number) => (
    <Card className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2"><span className={`h-2.5 w-2.5 rounded-full ${dot}`} /><h3 className="font-headline-sm text-headline-sm text-on-surface">{title} ({pct(p)})</h3></div>
        <span className="rounded bg-surface-container px-2 py-0.5 font-code-sm text-[11px] text-on-surface-variant">{items.filter((k) => k.after !== 'missing').length}/{items.length} present</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {items.map((k) => {
          const s = KW[k.after]
          const canConfirm = k.after === 'missing' && k.evidence_ids.length === 0 && !skills.some((x) => x.toLowerCase() === k.term.toLowerCase())
          return (
            <span key={k.term} title={s.tip + (k.evidence_ids.length && k.after === 'missing' ? ` · backed by ${k.evidence_ids.map((e) => labels[e]?.title ?? e).join(', ')}` : '')} className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 font-code-sm text-[11px] font-medium ${s.cls}`}>
              {k.term}
              <Icon name={s.icon} className="text-[13px]" />
              {canConfirm && <button type="button" onClick={() => onConfirm(k.term)} className="ml-0.5 underline">I have this</button>}
            </span>
          )
        })}
      </div>
    </Card>
  )
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      {list('Must-have keywords', 'bg-emerald-500', must, mustPct)}
      {list('Nice-to-have', 'bg-primary', nice, nicePct)}
      <p className="font-body-sm text-body-sm text-on-surface-variant md:col-span-2">Green: used in a bullet. Amber: only in the Skills list. Red: not found. Measured on the text extracted from your PDF, so what an ATS can read.</p>
    </div>
  )
}

function Guardrails({ run, skills, onConfirm }: { run: SavedRun; skills: string[]; onConfirm: (t: string) => void }) {
  const RULE: Record<string, string> = { invented_term: 'Unsupported skill or name', invented_number: 'Unsupported number', evidence_scope: 'Evidence used out of scope', locked: 'Locked section', unknown_target: 'Unknown target', structure: 'Structure', too_long: 'Too long', stuffing: 'Keyword stuffing', latex: 'Wrote LaTeX', empty: 'Empty text', duplicate: 'Duplicate change', unknown_evidence: 'Unknown evidence' }
  return (
    <div className="flex flex-col gap-4">
      <Card className="p-6">
        <h3 className="flex items-center gap-2 font-headline-sm text-headline-sm text-on-surface"><Icon name="security" className="text-[20px] text-error" /> Blocked edits <InfoTip align="left">Every edit the model proposes is checked in code. Anything not backed by your resume or context is refused and sent back with the reason.</InfoTip></h3>
        {run.blocked.length === 0 ? (
          <p className="mt-2 font-body-md text-body-md text-on-surface-variant">Nothing was blocked in this run.</p>
        ) : (
          <ul className="mt-3 flex flex-col divide-y divide-outline-variant/40">
            {run.blocked.map((b, i) => (
              <li key={i} className="flex flex-col gap-1.5 py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded border border-red-200 bg-error-container px-2 py-0.5 font-code-sm text-[11px] font-semibold text-on-error-container">{RULE[b.rule] ?? b.rule}</span>
                  {b.retried && <span className="font-body-sm text-body-sm text-on-surface-variant">The model was asked to try again without it.</span>}
                </div>
                <div className="font-body-md text-body-md text-on-surface">{b.message}</div>
                {b.text && <blockquote className="rounded-r-lg border-l-4 border-error bg-surface-container-low px-3 py-1.5 font-body-sm text-body-sm text-on-surface-variant">{plain(b.text)}</blockquote>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="p-6">
        <h3 className="flex items-center gap-2 font-headline-sm text-headline-sm text-on-surface"><Icon name="gpp_maybe" className="text-[20px] text-amber-600" /> Left out: no proof</h3>
        <p className="mt-1 font-body-sm text-body-sm text-on-surface-variant">The job asks for these, but nothing in your resume or context shows them. Confirm only what you could talk about in an interview.</p>
        {run.left_out.length === 0 ? (
          <p className="mt-3 font-body-md text-body-md text-on-surface-variant">Every job keyword was on your resume or backed by your context.</p>
        ) : (
          <div className="mt-3 flex flex-wrap gap-2">
            {run.left_out.map((k) => {
              const done = skills.some((s) => s.toLowerCase() === k.term.toLowerCase())
              return (
                <span key={k.term} className="inline-flex items-center gap-2 rounded-full border border-outline-variant bg-surface-container-low py-1 pl-3 pr-1.5 font-code-sm text-code-sm text-on-surface-variant">
                  {k.term}{k.must && <span className="h-1.5 w-1.5 rounded-full bg-primary-container" title="must-have" />}
                  <button type="button" disabled={done} onClick={() => onConfirm(k.term)} className="rounded-full bg-surface-container-lowest px-2.5 py-0.5 font-label-sm text-label-sm text-primary hover:bg-primary-fixed/40 disabled:text-emerald-700">{done ? 'confirmed' : 'I have this'}</button>
                </span>
              )
            })}
          </div>
        )}
      </Card>
      <Card className="p-6">
        <h3 className="mb-3 font-headline-sm text-headline-sm text-on-surface">Run details</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-left font-body-sm text-body-sm">
            <thead><tr className="border-b border-outline-variant/50 font-code-sm text-[11px] uppercase text-on-surface-variant"><th className="py-2 pr-4">Strategy</th><th className="py-2 pr-4">Score</th><th className="py-2 pr-4">Must-have</th><th className="py-2 pr-4">Applied</th><th className="py-2">Blocked</th></tr></thead>
            <tbody>
              {run.candidates.map((c) => (
                <tr key={c.arm} className={`border-b border-outline-variant/30 last:border-0 ${c.arm === run.arm ? 'font-semibold' : ''}`}>
                  <td className="py-2 pr-4">{c.arm}{c.arm === run.arm ? ' (used)' : ''}</td><td className="py-2 pr-4">{c.reward.toFixed(3)}</td><td className="py-2 pr-4">{pct(c.must_have)}</td><td className="py-2 pr-4">{c.applied}</td><td className="py-2">{c.blocked}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 font-body-sm text-body-sm text-on-surface-variant">{run.usage.model} · {run.usage.calls} calls · {run.usage.input_tokens.toLocaleString()} input and {run.usage.output_tokens.toLocaleString()} output tokens. Match figures are TailorTeX's own estimate on the PDF's text, not a score from any ATS vendor.</p>
      </Card>
    </div>
  )
}
