import { InfoTip, Icon } from '../ui'
import { pct } from '../format'

/** One score, before and after, on one line. Everything else lives under Details. */
export function ScoreHeader({ before, after, estimated, measured, mustCovered, mustTotal }: {
  before: number
  after: number
  /** While changes are ticked or unticked and not yet applied: what the score should become. */
  estimated: number | null
  /** False for runs saved before the composite score existed: the number shown is the must-have share. */
  measured: boolean
  mustCovered: number
  mustTotal: number
}) {
  const shown = estimated ?? after
  const delta = Math.round((shown - before) * 100)
  const pending = estimated !== null && Math.abs(estimated - after) > 0.0005
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-outline-variant/50 bg-surface-container-lowest p-5">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-[15px] text-on-surface-variant line-through decoration-outline-variant">{pct(before)}</span>
          <Icon name="arrow_forward" className="text-[18px] text-outline" />
          <span className={`font-mono text-[40px] font-bold leading-none tracking-tight ${pending ? 'text-primary' : 'text-on-surface'}`}>
            {pending && <span className="mr-1 text-[22px] font-medium text-on-surface-variant">~</span>}{pct(shown)}
          </span>
          {delta !== 0 && (
            <span className={`rounded border px-1.5 py-0.5 font-code-sm text-[12px] font-semibold ${delta > 0 ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-red-200 bg-error-container text-on-error-container'}`}>
              {delta > 0 ? '+' : ''}{delta}%
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 font-body-sm text-body-sm text-on-surface-variant">
          {pending ? 'Estimated: apply your choices to measure it' : `${mustCovered} of ${mustTotal} must-have skills shown in your resume`}
          <InfoTip align="right">
            {measured
              ? "Your ATS score: how well the job's keywords are covered (a keyword used in a bullet counts fully, only in the Skills list 60%), how closely your titles match, whether the PDF can be read, how full the page is, and how well the bullets are written. The keyword figures are TailorTeX's own estimate, not a score from any real ATS."
              : "This run predates the combined score, so this is the share of the job's must-have keywords your resume shows."}
          </InfoTip>
        </div>
      </div>
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-surface-variant">
        <div className="h-full bg-outline" style={{ width: `${Math.min(before, shown) * 100}%` }} />
        {shown > before && <div className="h-full bg-emerald-500" style={{ width: `${(shown - before) * 100}%` }} />}
        {shown < before && <div className="h-full bg-error/60" style={{ width: `${(before - shown) * 100}%` }} />}
      </div>
    </div>
  )
}
