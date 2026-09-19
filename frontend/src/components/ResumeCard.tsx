import { useRef, useState } from 'react'
import type { Outline } from '../api'
import { Icon, Spinner } from './Icons'

type Props = {
  tex: string
  setTex: (t: string) => void
  outline: Outline | null
  parsing: boolean
  parseError: string | null
  onFix: (fix: string) => void
  onTemplate: () => void
}

const TEMPLATE_NAMES: Record<string, string> = {
  jake: "Jake's Resume",
  'awesome-cv': 'Awesome-CV',
  moderncv: 'moderncv',
  generic: 'Custom template',
}

export function ResumeCard({ tex, setTex, outline, parsing, parseError, onFix, onTemplate }: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [showSource, setShowSource] = useState(!tex)
  const [showOutline, setShowOutline] = useState(false)
  const [fileError, setFileError] = useState<string | null>(null)

  const onFile = async (file: File | undefined) => {
    setFileError(null)
    if (!file) return
    if (!/\.(tex|txt)$/i.test(file.name)) {
      setFileError('Upload the main .tex file of your resume (Overleaf: Menu → Download → Source, then pick the main .tex).')
      return
    }
    if (file.size > 400_000) {
      setFileError('That file is larger than 400 KB.')
      return
    }
    setTex(await file.text())
    setShowSource(false)
  }

  const warnings = outline?.lint.filter((l) => l.severity === 'warn') ?? []
  const infos = outline?.lint.filter((l) => l.severity === 'info') ?? []

  return (
    <section className="card">
      <header className="card-head">
        <span className="step">2</span>
        <div>
          <h2>Your LaTeX resume</h2>
          <p className="muted">Your template stays byte-for-byte intact. Only bullets, the summary and skills lines change.</p>
        </div>
      </header>

      <div
        className="dropzone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault()
          onFile(e.dataTransfer.files[0])
        }}
      >
        <button type="button" className="btn secondary" onClick={() => fileRef.current?.click()}>
          <Icon name="upload" /> Upload .tex
        </button>
        <span className="muted small">or drop it here, or</span>
        <button type="button" className="link" onClick={() => { setShowSource(true); if (!tex) onTemplate() }}>
          {tex ? 'edit the source' : 'start from our ATS-safe template'}
        </button>
        <input ref={fileRef} type="file" accept=".tex,.txt" hidden onChange={(e) => onFile(e.target.files?.[0])} />
      </div>
      {fileError && <p className="status bad"><Icon name="alert" /> {fileError}</p>}

      {tex && (
        <div className="parse-summary">
          {parsing && <Spinner />}
          {parseError && <span className="bad"><Icon name="alert" /> {parseError}</span>}
          {outline && !parseError && (
            <>
              <span className="pill">{TEMPLATE_NAMES[outline.profile] ?? outline.profile}</span>
              <span>
                <strong>{outline.name || 'Resume'}</strong> · {outline.stats.sections} sections · {outline.stats.bullets} bullets ·{' '}
                {outline.stats.editable} editable
              </span>
              <button type="button" className="link" onClick={() => setShowOutline((s) => !s)}>
                {showOutline ? 'Hide' : 'Show'} what TailorTeX sees
              </button>
              <button type="button" className="link" onClick={() => setShowSource((s) => !s)}>
                {showSource ? 'Hide' : 'Show'} source
              </button>
            </>
          )}
        </div>
      )}

      {showOutline && outline && (
        <div className="outline">
          {outline.sections.map((s) => (
            <div key={s.id} className="outline-section">
              <div className="outline-title">
                {s.title} <span className="muted small">{s.kind}</span>
                {s.locked && <span className="pill muted-pill"><Icon name="lock" /> kept as is</span>}
              </div>
              {s.blocks.map((b) => (
                <div key={b.id} className={`outline-line ${b.locked ? 'locked' : ''}`}>
                  {b.label ? <strong>{b.label}: </strong> : null}
                  {b.text}
                </div>
              ))}
              {s.entries.map((e) => (
                <div key={e.id} className="outline-entry">
                  {e.heading && <div className="outline-heading">{e.heading}</div>}
                  {e.bullets.map((b) => (
                    <div key={b.id} className={`outline-line bullet ${b.locked ? 'locked' : ''}`} title={b.lock_reason ?? ''}>
                      {b.locked && <Icon name="lock" />} {b.text.replace(/\*\*/g, '')}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}

      {warnings.map((w) => (
        <div key={w.id} className="note warn-note">
          <Icon name="alert" />
          <span>{w.message}</span>
          {w.fixable && (
            <button type="button" className="btn small" onClick={() => onFix(w.id)}>
              Fix it
            </button>
          )}
        </div>
      ))}
      {infos.map((w) => (
        <div key={w.id} className="note info-note">
          <Icon name="info" /> <span>{w.message}</span>
        </div>
      ))}

      {showSource && (
        <textarea
          className="code"
          value={tex}
          onChange={(e) => setTex(e.target.value)}
          placeholder="\documentclass{article} … paste your resume's LaTeX here"
          spellCheck={false}
          rows={14}
        />
      )}
    </section>
  )
}
