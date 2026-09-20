import { useState } from 'react'
import { Icon } from '../ui'

/** The resume as it will be, kept beside the changes so every tick has a visible effect. */
export function Preview({ pdfUrl, tex, busy, compileError }: { pdfUrl: string | null; tex: string; busy: boolean; compileError: string | null }) {
  const [view, setView] = useState<'pdf' | 'tex'>(pdfUrl ? 'pdf' : 'tex')
  const showing = view === 'pdf' && pdfUrl ? 'pdf' : 'tex'
  return (
    <div className="flex h-[calc(100vh-7.5rem)] min-h-[420px] flex-col overflow-hidden rounded-xl border border-outline-variant/60 bg-surface-container-lowest shadow-sm">
      <div className="flex items-center justify-between gap-2 border-b border-outline-variant/50 px-3 py-2">
        <span className="font-label-md text-label-md font-semibold text-on-surface">Your resume</span>
        <div role="tablist" className="flex rounded-lg bg-surface-container p-0.5">
          {(['pdf', 'tex'] as const).map((v) => (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={showing === v}
              disabled={v === 'pdf' && !pdfUrl}
              onClick={() => setView(v)}
              className={`rounded-md px-2.5 py-1 font-label-sm text-label-sm transition-colors disabled:opacity-40 ${showing === v ? 'bg-surface-container-lowest font-semibold text-on-surface shadow-sm' : 'text-on-surface-variant hover:text-on-surface'}`}
            >
              {v === 'pdf' ? 'PDF' : 'LaTeX'}
            </button>
          ))}
        </div>
      </div>
      <div className="relative min-h-0 flex-1">
        {showing === 'pdf' && pdfUrl ? (
          <iframe title="Your tailored resume" src={pdfUrl} className="h-full w-full bg-white" />
        ) : (
          <div className="h-full overflow-auto bg-surface-container-low">
            {!pdfUrl && (
              <p className="flex items-start gap-2 border-b border-outline-variant/40 bg-amber-50 px-3 py-2 font-body-sm text-body-sm text-amber-900">
                <Icon name="warning" className="mt-0.5 text-[16px]" />
                {compileError ?? "There is no PDF for this run. Copy the LaTeX into Overleaf to compile it."}
              </p>
            )}
            <pre className="whitespace-pre-wrap break-words p-3 font-code-sm text-code-sm text-on-surface"><code>{tex}</code></pre>
          </div>
        )}
        {busy && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface-container-lowest/70 backdrop-blur-[1px]" role="status">
            <span className="inline-flex items-center gap-2 rounded-full bg-inverse-surface px-4 py-2 font-body-sm text-body-sm text-inverse-on-surface shadow-lg">
              <Icon name="progress_activity" className="animate-spin text-[16px]" /> Updating your resume…
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
