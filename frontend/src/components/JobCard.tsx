type Props = {
  jd: string
  setJd: (s: string) => void
  candidates: number
  setCandidates: (n: number) => void
  compilePdf: boolean
  setCompilePdf: (b: boolean) => void
  pageLimit: number | null
  setPageLimit: (n: number | null) => void
  texAvailable: boolean
}

export function JobCard({ jd, setJd, candidates, setCandidates, compilePdf, setCompilePdf, pageLimit, setPageLimit, texAvailable }: Props) {
  const words = jd.trim() ? jd.trim().split(/\s+/).length : 0
  return (
    <section className="card">
      <header className="card-head">
        <span className="step">4</span>
        <div>
          <h2>Job description</h2>
          <p className="muted">Paste the full posting. It's treated as data: instructions hidden inside it are ignored.</p>
        </div>
      </header>
      <textarea value={jd} onChange={(e) => setJd(e.target.value)} rows={9} placeholder="Paste the job description here…" />
      <div className="hint right">{words ? `${words} words` : ''}</div>

      <div className="options">
        <div className="field">
          <span>Quality</span>
          <div className="segmented" role="radiogroup">
            <button type="button" role="radio" aria-checked={candidates === 1} className={candidates === 1 ? 'active' : ''} onClick={() => setCandidates(1)}>
              Fast
            </button>
            <button type="button" role="radio" aria-checked={candidates === 3} className={candidates === 3 ? 'active' : ''} onClick={() => setCandidates(3)}>
              Best of 3
            </button>
          </div>
          <span className="hint">{candidates === 3 ? 'Tries 3 strategies and keeps the best. Uses about 3× the tokens.' : 'One strategy, picked by what has worked before.'}</span>
        </div>
        <div className="field">
          <span>Page limit</span>
          <select value={pageLimit ?? ''} onChange={(e) => setPageLimit(e.target.value ? Number(e.target.value) : null)}>
            <option value="">Same as now</option>
            <option value="1">1 page</option>
            <option value="2">2 pages</option>
          </select>
        </div>
        <label className="check">
          <input type="checkbox" checked={compilePdf && texAvailable} disabled={!texAvailable} onChange={(e) => setCompilePdf(e.target.checked)} />
          Compile a PDF and check it like an ATS
          {!texAvailable && <span className="muted small"> (LaTeX isn't installed on this server)</span>}
        </label>
      </div>
    </section>
  )
}
