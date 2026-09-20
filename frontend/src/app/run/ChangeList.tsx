import { useState } from 'react'
import type { Change } from '../../api'
import { plain, wordDiff } from '../../util'
import { gainLabel } from '../format'
import { Badge, Button, Icon, TextArea } from '../ui'

export type Decision = { action: 'kept' | 'reverted' | 'edited'; text?: string }
export type Labels = Record<string, { title: string; url?: string | null }>

const OP: Record<Change['op'], string> = {
  rewrite: 'Reworded',
  add: 'New bullet',
  drop: 'Removed',
  drop_entry: 'Removed',
  reorder: 'Reordered',
  reorder_entries: 'Reordered',
}

/** The changes TailorTeX made, each one a checkbox: ticked means it is in your resume. */
export function ChangeList({ changes, decisions, onDecide, labels, onReviewOneByOne }: {
  changes: Change[]
  decisions: Record<number, Decision>
  onDecide: (id: number, d: Decision) => void
  labels: Labels
  onReviewOneByOne: () => void
}) {
  if (!changes.length) {
    return <p className="rounded-xl border border-outline-variant/50 bg-surface-container-lowest p-5 font-body-md text-body-md text-on-surface-variant">No changes were needed, or none passed the checks.</p>
  }
  const untouched = changes.every((c) => (decisions[c.id]?.action ?? 'kept') === 'kept')
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-headline-sm text-headline-sm text-on-surface">Changes made for this job</h2>
        {untouched && changes.length > 1 && (
          <button type="button" onClick={onReviewOneByOne} className="font-label-md text-label-md font-semibold text-primary hover:underline">
            Review one by one
          </button>
        )}
      </div>
      {changes.map((c) => <ChangeRow key={c.id} change={c} decision={decisions[c.id] ?? { action: 'kept' }} onDecide={(d) => onDecide(c.id, d)} labels={labels} />)}
    </div>
  )
}

function ChangeRow({ change, decision, onDecide, labels }: { change: Change; decision: Decision; onDecide: (d: Decision) => void; labels: Labels }) {
  const [editing, setEditing] = useState(false)
  const on = decision.action !== 'reverted'
  const current = decision.action === 'edited' ? decision.text ?? change.after : change.after
  const [draft, setDraft] = useState(plain(current))
  const editable = change.op === 'rewrite' || change.op === 'add'
  const where = [change.section, change.heading].filter(Boolean).join(' › ')
  const gain = gainLabel(change.gain ?? 0)
  const short = (t: string) => (plain(t).length > 90 ? `${plain(t).slice(0, 88)}…` : plain(t))

  return (
    <div className={`flex gap-3 rounded-xl border p-4 transition-colors ${on ? 'border-outline-variant/60 bg-surface-container-lowest' : 'border-outline-variant/40 bg-surface-container-low/60'}`}>
      <button
        type="button"
        role="checkbox"
        aria-checked={on}
        aria-label={on ? 'Included in your resume. Click to leave this change out.' : 'Left out. Click to include this change.'}
        onClick={() => onDecide(on ? { action: 'reverted' } : { action: 'kept' })}
        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors ${on ? 'border-primary bg-primary text-on-primary' : 'border-outline bg-surface-container-lowest text-transparent hover:border-primary'}`}
      >
        <Icon name="check" className="text-[15px]" />
      </button>
      <div className={`flex min-w-0 flex-1 flex-col gap-2 ${on ? '' : 'opacity-60'}`}>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-label-md text-label-md font-semibold text-on-surface">{OP[change.op]}</span>
          {where && <span className="truncate font-code-sm text-code-sm text-on-surface-variant">{where}</span>}
          {change.source === 'fit' && <Badge tone="warn">to fit the page</Badge>}
          {decision.action === 'edited' && <Badge tone="accent">your wording</Badge>}
          {gain && <span className={`ml-auto rounded px-1.5 py-0.5 font-code-sm text-[11px] font-semibold ${(change.gain ?? 0) > 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-error-container text-on-error-container'}`}>{gain} ATS</span>}
        </div>

        {editing ? (
          <div className="flex flex-col gap-2">
            <TextArea rows={3} value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Your version" />
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" disabled={!draft.trim()} onClick={() => { onDecide({ action: 'edited', text: draft.trim() }); setEditing(false) }}>Save my version</Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
              <span className="font-body-sm text-body-sm text-on-surface-variant">Your own words aren't checked against your context: you're vouching for them.</span>
            </div>
          </div>
        ) : (
          <div className="font-body-md text-body-md leading-relaxed text-on-surface">
            {change.op === 'rewrite' && wordDiff(plain(change.before), plain(current)).map((p, i) => (
              <span key={i} className={p.kind === 'del' ? 'rounded bg-error-container px-0.5 text-on-error-container line-through' : p.kind === 'ins' ? 'rounded bg-emerald-50 px-0.5 font-medium text-emerald-900' : ''}>{p.text}</span>
            ))}
            {change.op === 'add' && <span className="rounded bg-emerald-50 px-0.5 font-medium text-emerald-900">{plain(current)}</span>}
            {(change.op === 'drop' || change.op === 'drop_entry') && <span className="rounded bg-error-container px-0.5 text-on-error-container line-through">{plain(change.before)}</span>}
            {(change.op === 'reorder' || change.op === 'reorder_entries') && change.before_list && change.after_list && (
              <ol className="list-decimal pl-5">{change.after_list.map((t, i) => <li key={i} className={change.before_list?.[i] !== t ? 'font-medium text-primary' : 'text-on-surface-variant'}>{short(t)}</li>)}</ol>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5 font-body-sm text-body-sm text-on-surface-variant">
            {change.terms && change.terms.length > 0 && <span>Adds <span className="font-medium text-on-surface">{change.terms.join(', ')}</span></span>}
            {change.evidence.length > 0 && (
              <span className="inline-flex items-center gap-1">
                <Icon name="verified_user" className="text-[14px] text-emerald-600" /> from{' '}
                {change.evidence.map((eid, i) => <span key={eid}>{i > 0 && ', '}{labels[eid]?.title ?? eid}</span>)}
              </span>
            )}
            {change.reason && !change.terms?.length && <span className="italic">{change.reason}</span>}
          </div>
          {editable && on && !editing && (
            <button type="button" onClick={() => { setDraft(plain(current)); setEditing(true) }} className="inline-flex items-center gap-1 font-label-sm text-label-sm text-on-surface-variant hover:text-primary">
              <Icon name="edit" className="text-[14px]" /> {decision.action === 'edited' ? 'Edit again' : 'Edit'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
