import type { Keyword, Metrics, TermStatus } from '../../api'
import { plain } from '../../util'
import { pct, qualityOf } from '../format'
import { Badge, Card, Icon } from '../ui'
import type { SavedRun } from '../client'

const KW: Record<TermStatus, { cls: string; icon: string; tip: string }> = {
  context: { cls: 'border-emerald-200 bg-emerald-50 text-emerald-700', icon: 'check', tip: 'Used in a bullet' },
  listed: { cls: 'border-amber-200 bg-amber-50 text-amber-800', icon: 'remove', tip: 'Only in the Skills list' },
  missing: { cls: 'border-red-200 bg-error-container text-on-error-container', icon: 'close', tip: 'Not found' },
}

const RULE: Record<string, string> = {
  invented_term: 'Not on your resume or context', invented_number: 'Number not backed', evidence_scope: 'Evidence used in the wrong place',
  locked: 'Locked section', unknown_target: 'Unknown target', structure: 'Structure', too_long: 'Too long', stuffing: 'Keyword stuffing',
  latex: 'Wrote LaTeX', empty: 'Empty text', duplicate: 'Duplicate change', unknown_evidence: 'Unknown evidence', coverage: 'Would lose a required skill',
}

/** Everything that explains the score. Closed by default: it is for checking, not for reading first. */
export function Details({ run, after, before }: { run: SavedRun; after: Metrics; before: Metrics }) {
  const must = run.keywords.filter((k) => k.must)
  const nice = run.keywords.filter((k) => !k.must)
  const q = qualityOf(after)
  const parse = after.checks
  return (
    <details className="group rounded-xl border border-outline-variant/60 bg-surface-container-lowest">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-5 py-4 font-headline-sm text-headline-sm text-on-surface">
        <span className="flex items-center gap-2"><Icon name="analytics" className="text-[20px] text-on-surface-variant" /> Details behind the score</span>
        <Icon name="expand_more" className="text-[20px] text-on-surface-variant transition-transform group-open:rotate-180" />
      </summary>
      <div className="flex flex-col gap-space-lg border-t border-outline-variant/40 p-5">
        <Section title="Keywords from the job" note={`Must-have ${pct(after.must_have)} · nice-to-have ${pct(after.nice_to_have)}. Green: used in a bullet. Amber: only in the Skills list (counts 60%). Red: not found. Measured on the text extracted from your PDF.`}>
          <div className="flex flex-wrap gap-2">
            {[...must, ...nice].map((k: Keyword) => (
              <span key={k.term} title={KW[k.after].tip} className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 font-code-sm text-[11px] font-medium ${KW[k.after].cls}`}>
                {k.term}<Icon name={KW[k.after].icon} className="text-[13px]" />{!k.must && <span className="opacity-60">nice</span>}
              </span>
            ))}
          </div>
        </Section>

        {q.checks.length > 0 && (
          <Section title="How the resume is written" note="These help on any job, not just this one.">
            <ul className="flex flex-col gap-1.5">
              {q.checks.map((c) => (
                <li key={c.id} className="flex items-start gap-2 font-body-sm text-body-sm">
                  <Icon name={c.ok ? 'check_circle' : 'error'} fill className={`mt-0.5 text-[16px] ${c.ok ? 'text-emerald-600' : 'text-amber-600'}`} />
                  <span><span className="font-medium text-on-surface">{c.label}.</span> <span className="text-on-surface-variant">{c.ok ? '' : c.detail}</span></span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        <Section title="Can an ATS read the PDF?" note={parse.length ? undefined : 'Needs a compiled PDF. Your resume did not compile, so these checks did not run.'}>
          {parse.length > 0 && (
            <ul className="flex flex-col gap-1.5">
              {parse.map((c) => (
                <li key={c.id} className="flex items-start gap-2 font-body-sm text-body-sm">
                  <Icon name={c.ok ? 'check_circle' : 'error'} fill className={`mt-0.5 text-[16px] ${c.ok ? 'text-emerald-600' : 'text-amber-600'}`} />
                  <span><span className="font-medium text-on-surface">{c.label}.</span> <span className="text-on-surface-variant">{c.ok ? '' : c.detail}</span></span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 font-body-sm text-body-sm text-on-surface-variant">
            {after.pages !== null ? `${after.pages} page${after.pages === 1 ? '' : 's'} (limit ${run.page_limit}), ${pct(after.page_fill)} of the last page filled. ` : ''}
            Title match {pct(before.title)} → {pct(after.title)}: TailorTeX never rewrites a job title, so this only moves if you change it.
          </p>
        </Section>

        {run.blocked.length > 0 && (
          <Section title="Edits that were refused" note="Each was checked against your resume and context. Anything they don't back is refused, so the resume never claims something you can't defend.">
            <ul className="flex flex-col divide-y divide-outline-variant/40">
              {run.blocked.map((b, i) => (
                <li key={i} className="flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0">
                  <span className="inline-flex w-fit rounded border border-red-200 bg-error-container px-2 py-0.5 font-code-sm text-[11px] font-semibold text-on-error-container">{RULE[b.rule] ?? b.rule}</span>
                  <span className="font-body-md text-body-md text-on-surface">{b.message}</span>
                  {b.text && <span className="rounded-r-lg border-l-4 border-error bg-surface-container-low px-3 py-1.5 font-body-sm text-body-sm text-on-surface-variant">{plain(b.text)}</span>}
                </li>
              ))}
            </ul>
          </Section>
        )}

        <p className="font-body-sm text-body-sm text-on-surface-variant">
          <Badge tone="neutral">{run.engine}</Badge> {run.usage.model} · {run.usage.calls} calls · {run.usage.input_tokens.toLocaleString()} tokens in, {run.usage.output_tokens.toLocaleString()} out. The match figures are TailorTeX's own estimate, not a score from any ATS vendor.
        </p>
      </div>
    </details>
  )
}

function Section({ title, note, children }: { title: string; note?: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-label-md text-label-md font-semibold text-on-surface">{title}</h3>
      {note && <p className="font-body-sm text-body-sm text-on-surface-variant">{note}</p>}
      {children}
    </div>
  )
}

export { Card }
