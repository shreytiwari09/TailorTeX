import { useEffect, useMemo, useState } from 'react'
import type { Keyword, Metrics, Result, Suggestion, TermStatus } from '../api'
import { base64ToBlob, pct } from '../util'
import { ChangeCard, type Decision } from './ChangeCard'
import { Icon, Spinner } from './Icons'

export type View = { tex: string; pdf: string | null; after: Metrics; warnings: string[] }

type Props = {
  result: Result
  view: View
  decisions: Record<number, Decision>
  setDecision: (id: number, d: Decision) => void
  dirty: boolean
  rebuilding: boolean
  onRebuild: () => void
  evidenceLabels: Record<string, string>
  skills: string[]
  onConfirmSkill: (term: string) => void
  onDownloadPdf: () => void
  onDownloadTex: () => void
  onCopy: () => Promise<void>
  onOverleaf: () => void
}

type Tab = 'changes' | 'suggestions' | 'keywords' | 'guardrails' | 'pdf' | 'latex'

const STATUS: Record<TermStatus, { label: string; cls: string }> = {
  context: { label: 'In bullets', cls: 'good' },
  listed: { label: 'Skills only', cls: 'mid' },
  missing: { label: 'Missing', cls: 'none' },
}

const RULE_LABEL: Record<string, string> = {
  invented_term: 'Unsupported skill or name',
  invented_number: 'Unsupported number',
  evidence_scope: 'Evidence used out of scope',
  locked: 'Locked section',
  unknown_target: 'Unknown target',
  structure: 'Structure',
  too_long: 'Too long',
  stuffing: 'Keyword stuffing',
  latex: 'Wrote LaTeX',
  empty: 'Empty text',
  duplicate: 'Duplicate change',
  unknown_evidence: 'Unknown evidence',
}

export function Results(props: Props) {
  const { result, view, decisions, setDecision, dirty, rebuilding, onRebuild, evidenceLabels } = props
  const [tab, setTab] = useState<Tab>('changes')
  const [copied, setCopied] = useState(false)
  const pdfUrl = useMemo(() => (view.pdf ? URL.createObjectURL(base64ToBlob(view.pdf, 'application/pdf')) : null), [view.pdf])
  useEffect(() => () => { if (pdfUrl) URL.revokeObjectURL(pdfUrl) }, [pdfUrl])

  const before = result.before
  const after = view.after
  const kept = result.changes.filter((c) => decisions[c.id]?.action !== 'reverted').length
  const fromEvidence = result.keywords.filter((k) => k.before === 'missing' && k.after !== 'missing').map((k) => k.term)

  return (
    <section className="results">
      <div className="card results-head">
        <div className="row between wrap gap-s">
          <div>
            <h2>
              {result.analysis.title || 'Tailored resume'}
              {result.analysis.company && <span className="muted"> · {result.analysis.company}</span>}
            </h2>
            <p className="muted small">
              {result.changes.length} changes ({kept} kept) · {result.blocked.length} blocked by guardrails
              {fromEvidence.length > 0 && <> · added from your evidence: {fromEvidence.join(', ')}</>}
            </p>
          </div>
          <div className="row wrap gap-s actions">
            {view.pdf && (
              <button type="button" className="btn" onClick={props.onDownloadPdf}>
                <Icon name="download" /> PDF
              </button>
            )}
            <button type="button" className={view.pdf ? 'btn secondary' : 'btn'} onClick={props.onDownloadTex}>
              <Icon name="download" /> .tex
            </button>
            <button
              type="button"
              className="btn secondary"
              onClick={async () => {
                await props.onCopy()
                setCopied(true)
                setTimeout(() => setCopied(false), 1500)
              }}
            >
              <Icon name={copied ? 'check' : 'copy'} /> {copied ? 'Copied' : 'Copy LaTeX'}
            </button>
            <button type="button" className="btn secondary" onClick={props.onOverleaf}>
              <Icon name="external" /> Overleaf
            </button>
          </div>
        </div>

        <div className="scores">
          <Score label="Must-have keywords" before={before.must_have} after={after.must_have} />
          <Score label="Nice-to-have keywords" before={before.nice_to_have} after={after.nice_to_have} />
          <Score label="Job title match" before={before.title} after={after.title} />
          <Score label="ATS parse health" before={before.health} after={after.health} checks={after.checks} />
          <div className="score">
            <span className="score-label">Pages</span>
            <span className="score-value">{after.pages ?? '–'}</span>
            <span className="score-sub">
              {after.page_fill != null ? `last page ${pct(after.page_fill)} full` : 'not compiled'} · limit {result.page_limit}
            </span>
          </div>
        </div>
        <p className="hint">Match figures are TailorTeX's own estimate, measured on the text extracted from the compiled PDF. They aren't a score from any ATS vendor.</p>

        {(view.warnings.length > 0 || result.fit_note) && (
          <div className="stack-s">
            {result.fit_note && <div className="note info-note"><Icon name="info" /> {result.fit_note}</div>}
            {view.warnings.map((w, i) => (
              <div key={i} className="note warn-note"><Icon name="alert" /> <span>{w}</span></div>
            ))}
          </div>
        )}

        {dirty && (
          <div className="rebuild-bar">
            <span>You changed some decisions. Rebuild to apply them and recompile.</span>
            <button type="button" className="btn" disabled={rebuilding} onClick={onRebuild}>
              {rebuilding ? <Spinner /> : <Icon name="refresh" />} Rebuild with my choices
            </button>
          </div>
        )}
      </div>

      <div className="tabs" role="tablist">
        <TabButton id="changes" tab={tab} setTab={setTab} label={`Changes (${result.changes.length})`} />
        <TabButton id="suggestions" tab={tab} setTab={setTab} label={`Suggestions (${result.suggestions.length})`} />
        <TabButton id="keywords" tab={tab} setTab={setTab} label="Keywords" />
        <TabButton id="guardrails" tab={tab} setTab={setTab} label={`Guardrails (${result.blocked.length + result.left_out.length})`} />
        <TabButton id="pdf" tab={tab} setTab={setTab} label="PDF" />
        <TabButton id="latex" tab={tab} setTab={setTab} label="LaTeX" />
      </div>

      {tab === 'changes' && (
        <div className="stack">
          {result.changes.length === 0 && <p className="card muted">No changes were needed, or none passed the guardrails.</p>}
          {result.changes.map((c) => (
            <ChangeCard key={c.id} change={c} decision={decisions[c.id] ?? { action: 'kept' }} onDecide={(d) => setDecision(c.id, d)} evidenceLabels={evidenceLabels} />
          ))}
        </div>
      )}

      {tab === 'suggestions' && <SuggestionList suggestions={result.suggestions} leftOut={result.left_out} skills={props.skills} onConfirm={props.onConfirmSkill} />}

      {tab === 'keywords' && <KeywordTable keywords={result.keywords} skills={props.skills} onConfirm={props.onConfirmSkill} evidenceLabels={evidenceLabels} />}

      {tab === 'guardrails' && (
        <div className="stack">
          <div className="card">
            <h3><Icon name="shield" /> Blocked edits</h3>
            <p className="muted small">Every edit the model proposed is checked in code. These were refused and sent back to the model with the reason.</p>
            {result.blocked.length === 0 && <p className="muted">Nothing was blocked in this run.</p>}
            <ul className="blocked">
              {result.blocked.map((b, i) => (
                <li key={i}>
                  <div className="row wrap gap-s">
                    <span className="pill bad-pill">{RULE_LABEL[b.rule] ?? b.rule}</span>
                    <span className="muted small">{b.op} · attempt {b.attempt}{b.retried ? ', sent back to the model' : ''}</span>
                  </div>
                  <div>{b.message}</div>
                  {b.text && <blockquote>{b.text.replace(/\*\*/g, '')}</blockquote>}
                </li>
              ))}
            </ul>
          </div>
          <div className="card">
            <h3><Icon name="target" /> Left out: no evidence</h3>
            <p className="muted small">
              The job asks for these, but nothing on your resume or in your evidence shows them, so TailorTeX didn't add them. If you really have one, confirm it and run again.
            </p>
            {result.left_out.length === 0 && <p className="muted">Every job keyword was either on your resume or backed by evidence.</p>}
            <div className="chips">
              {result.left_out.map((k) => {
                const confirmed = props.skills.some((s) => s.toLowerCase() === k.term.toLowerCase())
                return (
                  <span key={k.term} className="chip gap-missing">
                    {k.term}
                    {k.must && <span className="must-dot" />}
                    <button type="button" className="chip-action" disabled={confirmed} onClick={() => props.onConfirmSkill(k.term)}>
                      {confirmed ? 'confirmed' : 'I have this'}
                    </button>
                  </span>
                )
              })}
            </div>
          </div>
          <div className="card">
            <h3><Icon name="layers" /> Run details</h3>
            <table className="table compact">
              <thead>
                <tr><th>Strategy</th><th>Score</th><th>Must-have</th><th>Applied</th><th>Blocked</th></tr>
              </thead>
              <tbody>
                {result.candidates.map((c) => (
                  <tr key={c.arm} className={c.arm === result.arm ? 'chosen' : ''}>
                    <td>{c.arm}{c.arm === result.arm ? ' (used)' : ''}</td>
                    <td>{c.reward.toFixed(3)}</td>
                    <td>{pct(c.must_have)}</td>
                    <td>{c.applied}</td>
                    <td>{c.blocked}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted small">
              {result.usage.model} · {result.usage.calls} calls · {result.usage.input_tokens.toLocaleString()} input and {result.usage.output_tokens.toLocaleString()} output tokens.
              The strategy is chosen by a bandit that learns from what people keep and revert.
            </p>
          </div>
        </div>
      )}

      {tab === 'pdf' && (
        <div className="card pdf-card">
          {pdfUrl ? <iframe title="Tailored resume PDF" src={pdfUrl} className="pdf-frame" /> : <p className="muted">No PDF for this run. Turn on "Compile a PDF" to get one, or open the .tex in Overleaf.</p>}
        </div>
      )}

      {tab === 'latex' && (
        <div className="card">
          <pre className="code-view"><code>{view.tex}</code></pre>
        </div>
      )}
    </section>
  )
}

function TabButton({ id, tab, setTab, label }: { id: Tab; tab: Tab; setTab: (t: Tab) => void; label: string }) {
  return (
    <button type="button" role="tab" aria-selected={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
      {label}
    </button>
  )
}

function Score({ label, before, after, checks }: { label: string; before: number | null; after: number | null; checks?: Metrics['checks'] }) {
  const delta = before != null && after != null ? Math.round((after - before) * 100) : null
  const failing = checks?.filter((c) => !c.ok) ?? []
  return (
    <div className="score" title={checks?.map((c) => `${c.ok ? '✓' : '✗'} ${c.label}: ${c.detail}`).join('\n')}>
      <span className="score-label">{label}</span>
      <span className="score-value">
        {pct(after)}
        {delta !== null && delta !== 0 && <span className={`delta ${delta > 0 ? 'up' : 'down'}`}>{delta > 0 ? '+' : ''}{delta}</span>}
      </span>
      <div className="bar">
        <span className="bar-before" style={{ width: `${Math.round((before ?? 0) * 100)}%` }} />
        <span className="bar-after" style={{ width: `${Math.round((after ?? 0) * 100)}%` }} />
      </div>
      <span className="score-sub">
        {checks ? (checks.length ? (failing.length ? `${failing.length} check${failing.length > 1 ? 's' : ''} failing` : `all ${checks.length} checks pass`) : 'not compiled') : `was ${pct(before)}`}
      </span>
    </div>
  )
}

function KeywordTable({ keywords, skills, onConfirm, evidenceLabels }: { keywords: Keyword[]; skills: string[]; onConfirm: (t: string) => void; evidenceLabels: Record<string, string> }) {
  return (
    <div className="card">
      <table className="table">
        <thead>
          <tr>
            <th>Keyword</th>
            <th>Type</th>
            <th>Before</th>
            <th>After</th>
            <th>Why</th>
          </tr>
        </thead>
        <tbody>
          {keywords.map((k) => {
            const confirmed = skills.some((s) => s.toLowerCase() === k.term.toLowerCase())
            return (
              <tr key={k.term}>
                <td>
                  <strong>{k.term}</strong>
                  <span className="weight" aria-label={`weight ${k.weight}`}>{'●'.repeat(k.weight)}</span>
                </td>
                <td>{k.must ? <span className="pill accent">must</span> : <span className="pill">nice</span>}</td>
                <td><span className={`status-pill ${STATUS[k.before].cls}`}>{STATUS[k.before].label}</span></td>
                <td><span className={`status-pill ${STATUS[k.after].cls}`}>{STATUS[k.after].label}</span></td>
                <td className="muted small">
                  {k.in_pdf === false && k.after !== 'missing' ? 'In the source but not readable in the PDF text. ' : ''}
                  {k.gap === 'evidence' && `Backed by ${k.evidence_ids.map((id) => evidenceLabels[id] ?? id).join(', ')}`}
                  {k.gap === 'missing' && k.after === 'missing' && (
                    <>
                      No evidence.{' '}
                      <button type="button" className="link" disabled={confirmed} onClick={() => onConfirm(k.term)}>
                        {confirmed ? 'Confirmed' : 'I have this'}
                      </button>
                    </>
                  )}
                  {k.gap === 'present' && k.before === k.after && 'Already there'}
                  {k.gap === 'present' && k.before !== k.after && 'Moved into context'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="hint">In bullets = used in context (what recruiters and semantic screeners reward). Skills only = listed but not shown in use.</p>
    </div>
  )
}

const SOURCE: Record<string, string> = { linkedin: 'LinkedIn', portfolio: 'Portfolio', github: 'GitHub', fact: 'Fact', skill: 'Skills' }

function SuggestionList({ suggestions, leftOut, skills, onConfirm }: { suggestions: Suggestion[]; leftOut: Result['left_out']; skills: string[]; onConfirm: (t: string) => void }) {
  const unconfirmed = leftOut.filter((k) => !skills.some((s) => s.toLowerCase() === k.term.toLowerCase()))
  return (
    <div className="stack">
      <div className="card">
        <h3><Icon name="spark" /> From your background</h3>
        <p className="muted small">
          Projects, roles and skills from your LinkedIn, portfolio, GitHub and facts that match this job but weren't on your resume.
        </p>
        {suggestions.length === 0 && (
          <p className="muted">Nothing from your background adds new keywords for this job. Add your LinkedIn, portfolio or GitHub in step 3 to get suggestions.</p>
        )}
        {suggestions.map((s) => (
          <div key={s.id} className="suggestion">
            <div className="row wrap gap-s">
              <span className="pill">{SOURCE[s.source] ?? s.source}</span>
              <strong>{s.id === 'skills' ? 'Skills you confirmed' : s.title || s.id}</strong>
              {s.url && <a className="muted small" href={s.url} target="_blank" rel="noreferrer"><Icon name="external" /></a>}
              {s.cited && <span className="pill accent">used in this version</span>}
            </div>
            {s.added.length > 0 && (
              <div className="chips">
                <span className="muted small">Added:</span>
                {s.added.map((t) => <span key={t} className="chip gap-present">{t}{s.must.includes(t) && <span className="must-dot" />}</span>)}
              </div>
            )}
            {s.still_missing.length > 0 && (
              <div className="chips">
                <span className="muted small">Could still add:</span>
                {s.still_missing.map((t) => <span key={t} className="chip gap-evidence">{t}{s.must.includes(t) && <span className="must-dot" />}</span>)}
              </div>
            )}
            {s.still_missing.length > 0 && (
              <p className="hint">
                {s.source === 'github' || s.source === 'portfolio'
                  ? 'Worth a spot in Projects. Try "Best of 3", which includes the evidence-first strategy, or add it yourself in Overleaf.'
                  : 'Try "Best of 3", which includes the evidence-first strategy, or mention it yourself.'}
              </p>
            )}
          </div>
        ))}
      </div>
      {unconfirmed.length > 0 && (
        <div className="card">
          <h3><Icon name="target" /> Do you have these?</h3>
          <p className="muted small">The job asks for these and nothing in your resume or background shows them. Only confirm the ones you could talk about in an interview.</p>
          <div className="chips">
            {unconfirmed.map((k) => (
              <span key={k.term} className="chip gap-missing">
                {k.term}
                {k.must && <span className="must-dot" />}
                <button type="button" className="chip-action" onClick={() => onConfirm(k.term)}>I have this</button>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
