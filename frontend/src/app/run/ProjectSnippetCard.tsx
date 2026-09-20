import { useState } from 'react'
import { openInOverleaf } from '../../util'
import type { ProjectSnippet } from '../client'
import { gainLabel } from '../format'
import { Badge, Button, Icon } from '../ui'

/**
 * A separate project, written as LaTeX in the resume's own style.
 *
 * TailorTeX can't create a new entry in someone's resume, so it does the next best thing: it writes the
 * block, checks it compiles, and says exactly where to paste it. The person adds it in Overleaf.
 */
export function ProjectSnippetCard({ snippet, engine, filename, onDismiss }: { snippet: ProjectSnippet; engine: string; filename: string; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false)
  const gain = snippet.ats_after - snippet.ats_before
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(snippet.latex)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      /* the code is selectable on the page, so the person can still copy it by hand */
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-primary-fixed bg-primary-fixed/15 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="accent">New project</Badge>
        <span className="font-label-md text-label-md font-semibold text-on-surface">{snippet.name}</span>
        {gain > 0.0004 && <span className="ml-auto rounded bg-emerald-100 px-1.5 py-0.5 font-code-sm text-[11px] font-semibold text-emerald-800">{gainLabel(gain)} ATS</span>}
      </div>

      <p className="font-body-md text-body-md text-on-surface">
        This is a separate project, and TailorTeX can't add a new entry to your resume by itself. So here is the code, written in the same style as your other projects. Add it in Overleaf:
      </p>

      <ol className="flex list-decimal flex-col gap-1 pl-5 font-body-md text-body-md text-on-surface">
        <li>Copy the code below.</li>
        <li>In Overleaf, open your resume and find your <span className="font-code-sm text-code-sm">Projects</span> section. Paste it <strong>{snippet.where}</strong>.</li>
        <li>Press Recompile.</li>
      </ol>

      <div className="relative">
        <pre className="max-h-[260px] overflow-auto whitespace-pre rounded-lg border border-outline-variant/50 bg-surface-container-low p-3 font-code-sm text-code-sm text-on-surface"><code>{snippet.latex}</code></pre>
        <Button size="sm" variant="secondary" className="absolute right-2 top-2" onClick={copy}>
          <Icon name={copied ? 'check' : 'content_copy'} className="text-[16px]" /> {copied ? 'Copied' : 'Copy code'}
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => openInOverleaf(snippet.tex_with_project, `${filename}.tex`, engine)}>
          <Icon name="open_in_new" className="text-[16px]" /> Open my resume in Overleaf with it added
        </Button>
        <Button size="sm" variant="ghost" onClick={onDismiss}>Done</Button>
      </div>

      <div className="flex flex-col gap-1 font-body-sm text-body-sm text-on-surface-variant">
        {snippet.compiles === true && (
          <span className="flex items-center gap-1.5">
            <Icon name="check_circle" fill className="text-[16px] text-emerald-600" />
            Checked: your resume still compiles with it{snippet.pages ? `, at ${snippet.pages} page${snippet.pages === 1 ? '' : 's'}` : ''}.
          </span>
        )}
        {snippet.compiles === false && (
          <span className="flex items-center gap-1.5 text-amber-800">
            <Icon name="warning" className="text-[16px]" /> The resume didn't compile with this added. Check the pasted code for a missing brace.
          </span>
        )}
        {snippet.over_limit && (
          <span className="flex items-center gap-1.5 text-amber-800">
            <Icon name="warning" className="text-[16px]" /> With it, your resume runs to {snippet.pages} pages and your limit is {snippet.page_limit}. Drop your weakest bullet, or shorten a long one.
          </span>
        )}
        {gain > 0.0004 && snippet.terms.length > 0 && <span>Adds <strong className="text-on-surface">{snippet.terms.join(', ')}</strong> in a bullet, worth more to an ATS than in a skills list.</span>}
      </div>

      <details className="font-body-sm text-body-sm text-on-surface-variant">
        <summary className="cursor-pointer font-label-md text-label-md font-semibold text-on-surface">Why this is safe for an ATS</summary>
        <ul className="mt-1.5 list-disc pl-5">
          <li>Plain text only: no tables, columns, icons or images, so a parser reads it in order.</li>
          <li>The project has a name, a date range and a <span className="font-code-sm">Tech</span> line in the same format as your other projects.</li>
          <li>Skills appear inside bullets, where they score full marks, as well as in the Tech line.</li>
          <li>Each bullet says what you built, how, and what came of it, using only what you told us.</li>
        </ul>
      </details>
    </div>
  )
}
