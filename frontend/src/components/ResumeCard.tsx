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

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
const MOD = isMac ? '⌘' : 'Ctrl+'

export function ResumeCard({ tex, setTex, outline, parsing, parseError, onFix, onTemplate }: Props) {
  const fileRef = useRef<HTMLInputElement>(null)
  // The paste box stays open while the user is working in it; it starts closed when a resume is already loaded.
  const [editorOpen, setEditorOpen] = useState(!tex.trim())
  const [showOutline, setShowOutline] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const onFile = async (file: File | undefined) => {
    setMessage(null)
    if (!file) return
    if (!/\.(tex|txt)$/i.test(file.name)) {
      setMessage('Pick the main .tex file of your resume.')
      return
    }
    if (file.size > 400_000) {
      setMessage('That file is larger than 400 KB.')
      return
    }
    setTex(await file.text())
    setEditorOpen(false)
  }

  const pasteFromClipboard = async () => {
    setMessage(null)
    try {
      const text = await navigator.clipboard.readText()
      if (!text.trim()) {
        setMessage(`Your clipboard is empty. In Overleaf, click in the editor, press ${MOD}A then ${MOD}C, and try again.`)
        return
      }
      if (!text.includes('\\')) {
        setMessage("What's on your clipboard doesn't look like LaTeX. Copy the code from Overleaf's editor, not the PDF preview.")
        return
      }
      setTex(text)
    } catch {
      setMessage(`Your browser blocked clipboard access. Click in the box below and press ${MOD}V instead.`)
    }
  }

  const warnings = outline?.lint.filter((l) => l.severity === 'warn') ?? []
  const infos = outline?.lint.filter((l) => l.severity === 'info') ?? []
  const lines = tex ? tex.split('\n').length : 0

  return (
    <section className="card">
      <header className="card-head">
        <span className="step">2</span>
        <div>
          <h2>Your LaTeX resume</h2>
          <p className="muted">Paste the code from Overleaf. Your template stays intact; only bullets, the summary and skills lines change.</p>
        </div>
      </header>

      {editorOpen ? (
        <div className="stack">
          <ol className="copy-steps">
            <li>In Overleaf, open your resume and click inside the code editor (the main <code>.tex</code> file).</li>
            <li>Press <kbd>{MOD}A</kbd> to select everything, then <kbd>{MOD}C</kbd> to copy.</li>
            <li>Paste it below with <kbd>{MOD}V</kbd>, or use the button.</li>
          </ol>
          <textarea
            className="code paste-box"
            value={tex}
            onChange={(e) => setTex(e.target.value)}
            placeholder={'Paste your resume\'s LaTeX here, from \\documentclass to \\end{document}'}
            spellCheck={false}
            rows={tex ? 14 : 8}
          />
          <div className="row wrap gap-s">
            <button type="button" className="btn secondary" onClick={pasteFromClipboard}>
              <Icon name="clipboard" /> Paste from clipboard
            </button>
            {tex.trim() && (
              <button type="button" className="btn" onClick={() => setEditorOpen(false)}>
                <Icon name="check" /> Done
              </button>
            )}
            <span className="muted small grow right">
              or{' '}
              <button type="button" className="link" onClick={() => fileRef.current?.click()}>upload a .tex file</button>
              {!tex.trim() && (
                <>
                  {' '}·{' '}
                  <button type="button" className="link" onClick={onTemplate}>start from our template</button>
                </>
              )}
            </span>
          </div>
        </div>
      ) : (
        <div className="loaded-resume">
          <Icon name="file" />
          <div className="grow">
            <strong>{outline?.name || 'Your resume'}</strong>
            <span className="muted small"> · {lines} lines of LaTeX</span>
          </div>
          <button type="button" className="btn secondary small" onClick={() => setEditorOpen(true)}>
            <Icon name="pencil" /> Edit LaTeX
          </button>
          <button
            type="button"
            className="btn ghost small"
            onClick={() => {
              setTex('')
              setEditorOpen(true)
              setShowOutline(false)
            }}
          >
            Replace
          </button>
        </div>
      )}
      <input ref={fileRef} type="file" accept=".tex,.txt" hidden onChange={(e) => onFile(e.target.files?.[0])} />
      {message && <p className="status bad"><Icon name="alert" /> {message}</p>}

      {tex.trim() && (
        <div className="parse-summary">
          {parsing && <Spinner />}
          {parseError && <span className="bad"><Icon name="alert" /> {parseError}</span>}
          {outline && !parseError && (
            <>
              <span className="pill">{TEMPLATE_NAMES[outline.profile] ?? outline.profile}</span>
              <span>
                {outline.stats.sections} sections · {outline.stats.bullets} bullets · {outline.stats.editable} editable
              </span>
              <button type="button" className="link" onClick={() => setShowOutline((s) => !s)}>
                {showOutline ? 'Hide' : 'Show'} what TailorTeX sees
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

      {tex.trim() &&
        warnings.map((w) => (
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
      {tex.trim() &&
        infos.map((w) => (
          <div key={w.id} className="note info-note">
            <Icon name="info" /> <span>{w.message}</span>
          </div>
        ))}
    </section>
  )
}
