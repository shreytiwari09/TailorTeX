import { useState } from 'react'
import type { Change } from '../api'
import { plain, wordDiff } from '../util'
import { Icon } from './Icons'

export type Decision = { action: 'kept' | 'reverted' | 'edited'; text?: string }

const OP_LABEL: Record<Change['op'], string> = {
  rewrite: 'Rewritten',
  add: 'Added',
  drop: 'Removed',
  reorder: 'Reordered',
  reorder_entries: 'Reordered',
  drop_entry: 'Removed',
}

type Props = {
  change: Change
  decision: Decision
  onDecide: (d: Decision) => void
  evidenceLabels: Record<string, string>
}

export function ChangeCard({ change, decision, onDecide, evidenceLabels }: Props) {
  const [editing, setEditing] = useState(false)
  const current = decision.action === 'edited' ? decision.text ?? change.after : change.after
  const [draft, setDraft] = useState(plain(current))
  const editable = change.op === 'rewrite' || change.op === 'add'
  const reverted = decision.action === 'reverted'
  const where = [change.section, change.heading].filter(Boolean).join(' › ')

  return (
    <article className={`change ${reverted ? 'reverted' : ''}`}>
      <header className="change-head">
        <span className={`op op-${change.op}`}>{OP_LABEL[change.op]}</span>
        {change.source === 'fit' && <span className="pill warn-pill">page fit</span>}
        {decision.action === 'edited' && <span className="pill accent">your edit</span>}
        <span className="where" title={where}>{where}</span>
      </header>

      {!editing && (
        <div className="change-body">
          {change.op === 'rewrite' && (
            <p className="diff">
              {wordDiff(plain(change.before), plain(current)).map((p, i) => (
                <span key={i} className={p.kind}>{p.text}</span>
              ))}
            </p>
          )}
          {change.op === 'add' && <p className="diff"><span className="ins">{plain(current)}</span></p>}
          {(change.op === 'drop' || change.op === 'drop_entry') && <p className="diff"><span className="del">{plain(change.before)}</span></p>}
          {(change.op === 'reorder' || change.op === 'reorder_entries') && change.before_list && change.after_list && (
            <div className="reorder">
              <ol>
                {change.before_list.map((t, i) => <li key={i}>{short(t)}</li>)}
              </ol>
              <Icon name="refresh" className="reorder-arrow" />
              <ol>
                {change.after_list.map((t, i) => {
                  const moved = change.before_list?.[i] !== t
                  return <li key={i} className={moved ? 'moved' : ''}>{short(t)}</li>
                })}
              </ol>
            </div>
          )}
        </div>
      )}

      {editing && (
        <div className="stack">
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} />
          <div className="row gap-s">
            <button type="button" className="btn small" disabled={!draft.trim()} onClick={() => { onDecide({ action: 'edited', text: draft.trim() }); setEditing(false) }}>
              Save my version
            </button>
            <button type="button" className="btn ghost small" onClick={() => setEditing(false)}>Cancel</button>
          </div>
          <span className="hint">Your own words aren't checked against the evidence: you're vouching for them.</span>
        </div>
      )}

      {(change.reason || change.evidence.length > 0) && (
        <p className="reason">
          {change.reason}
          {change.evidence.map((id) => (
            <span key={id} className="pill ev-pill" title={evidenceLabels[id] ?? id}>
              {evidenceLabels[id] ? `${id}: ${evidenceLabels[id]}` : id}
            </span>
          ))}
        </p>
      )}

      <footer className="change-actions">
        <button type="button" className={`seg ${decision.action === 'kept' ? 'on keep' : ''}`} onClick={() => onDecide({ action: 'kept' })}>
          <Icon name="check" /> Keep
        </button>
        <button type="button" className={`seg ${reverted ? 'on revert' : ''}`} onClick={() => onDecide({ action: 'reverted' })}>
          <Icon name="undo" /> Revert
        </button>
        {editable && (
          <button type="button" className={`seg ${decision.action === 'edited' ? 'on edit' : ''}`} onClick={() => { setDraft(plain(current)); setEditing(true) }}>
            <Icon name="pencil" /> Edit
          </button>
        )}
      </footer>
    </article>
  )
}

function short(t: string) {
  const s = plain(t)
  return s.length > 90 ? `${s.slice(0, 88)}…` : s
}
