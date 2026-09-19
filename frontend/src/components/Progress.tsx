import type { Gap, ProgressEvent } from '../api'
import { Icon, Spinner } from './Icons'

type Props = { events: ProgressEvent[]; running: boolean; model: string | null }

const GAP_LABEL = { present: 'On your resume', evidence: 'Backed by evidence', missing: 'No evidence' } as const

export function Progress({ events, running, model }: Props) {
  const gapsEvent = [...events].reverse().find((e) => e.stage === 'gaps')
  const gaps = (gapsEvent?.data.gaps as Gap[] | undefined) ?? []
  return (
    <section className="card progress-card" aria-live="polite">
      <header className="row between">
        <h2>{running ? 'Tailoring…' : 'Run log'}</h2>
        {model && <span className="pill">{model}</span>}
      </header>
      <ol className="timeline">
        {events.map((e, i) => {
          const last = i === events.length - 1
          const status = e.status === 'start' && (!last || !running) ? 'done' : e.status
          return (
            <li key={i} className={`t-${status}`}>
              <span className="t-icon">
                {status === 'start' ? <Spinner /> : status === 'warn' ? <Icon name="alert" /> : status === 'info' ? <Icon name="info" /> : <Icon name="check" />}
              </span>
              <span>{e.message}</span>
            </li>
          )
        })}
      </ol>
      {gaps.length > 0 && (
        <div className="gap-chips">
          {(['present', 'evidence', 'missing'] as const).map((k) => {
            const list = gaps.filter((g) => g.status === k)
            if (!list.length) return null
            return (
              <div key={k} className="gap-group">
                <span className="muted small">{GAP_LABEL[k]}</span>
                <div className="chips">
                  {list.map((g) => (
                    <span key={g.term} className={`chip gap-${k}`} title={g.must ? 'Must-have' : 'Nice-to-have'}>
                      {g.term}
                      {g.must && <span className="must-dot" aria-label="must-have" />}
                    </span>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
