import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { base64ToBlob, downloadBlob } from '../../util'
import { useAuth } from '../auth'
import { acct, type RunSummary } from '../client'
import { pct, timeAgo } from '../format'
import { Avatar, Badge, Button, Card, Icon, InfoTip, LinkButton, Notice, Skeleton } from '../ui'

export function Dashboard() {
  const { profile } = useAuth()
  const navigate = useNavigate()
  const [runs, setRuns] = useState<RunSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState('')

  useEffect(() => {
    let alive = true
    acct.runs().then((r) => alive && setRuns(r.runs)).catch((e: Error) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [])

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase()
    return (runs ?? []).filter((r) => !s || `${r.job_title} ${r.company ?? ''}`.toLowerCase().includes(s))
  }, [runs, q])

  const download = async (run: RunSummary, kind: 'pdf' | 'tex') => {
    try {
      const full = await acct.run(run.id)
      const name = run.filename || 'resume'
      if (kind === 'pdf' && full.pdf) downloadBlob(base64ToBlob(full.pdf, 'application/pdf'), `${name}.pdf`)
      else downloadBlob(new Blob([full.tex], { type: 'application/x-tex' }), `${name}.tex`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not download.')
    }
  }
  const remove = async (run: RunSummary) => {
    if (!window.confirm(`Delete the resume for ${run.company || run.job_title}?`)) return
    await acct.deleteRun(run.id).catch((e: Error) => setError(e.message))
    setRuns((list) => (list ?? []).filter((r) => r.id !== run.id))
  }

  const name = profile?.details.full_name || profile?.account.email || ''
  const contextCount = Object.values(profile?.context_counts ?? {}).reduce((a, b) => a + b, 0)
  const model = profile?.model

  return (
    <div className="flex flex-col gap-space-xl">
      <div className="flex flex-col items-start justify-between gap-space-md rounded-2xl bg-surface-container-low p-space-lg shadow-sm md:flex-row md:items-center">
        <div className="flex items-center gap-space-md">
          <Avatar name={name} url={profile?.account.avatar_url} size={64} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-headline-md text-headline-md text-on-surface">{name}</span>
              <Link to="/settings" className="inline-flex items-center gap-0.5 font-label-sm text-label-sm text-primary hover:underline">Edit profile <Icon name="north_east" className="text-[14px]" /></Link>
            </div>
            <div className="flex flex-wrap items-center gap-x-2 font-body-md text-body-md text-on-surface-variant">
              {profile?.details.headline && <span>{profile.details.headline}</span>}
              {profile?.details.headline && profile?.details.location && <span aria-hidden="true">•</span>}
              {profile?.details.location && <span className="inline-flex items-center gap-1"><Icon name="location_on" className="text-[16px]" />{profile.details.location}</span>}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Chip icon="description" to="/settings">{profile?.resume_tex.trim() ? 'Reference resume ready' : 'No resume yet'}</Chip>
          <Chip icon="database" to="/context">{contextCount} context {contextCount === 1 ? 'entry' : 'entries'}</Chip>
          <Chip icon="psychology" to="/settings">{model?.model ?? model?.provider ?? 'No model yet'}</Chip>
        </div>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="mb-1 flex items-center gap-2 font-label-sm text-label-sm uppercase tracking-wider text-primary-container">Your resumes</div>
          <h1 className="flex items-center gap-2 font-headline-lg-mobile text-headline-lg-mobile tracking-tight text-on-surface md:font-headline-lg md:text-headline-lg">
            Tailored resumes
            <InfoTip align="left">The percentage is the share of the job's must-have keywords found in your resume, measured on the text a parser extracts from the PDF.</InfoTip>
          </h1>
        </div>
        <LinkButton to="/new" size="lg"><Icon name="add" className="text-[20px]" /> New tailored resume</LinkButton>
      </div>

      {(runs?.length ?? 0) > 0 && (
        <div className="relative max-w-[520px]">
          <Icon name="search" className="absolute left-4 top-1/2 -translate-y-1/2 text-[20px] text-outline" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search jobs or companies" aria-label="Search resumes" className="w-full rounded-full bg-surface-container-low py-2.5 pl-11 pr-4 font-body-md text-body-md text-on-surface outline-none transition placeholder:text-outline focus:ring-4 focus:ring-primary-container/10" />
        </div>
      )}
      {error && <Notice tone="bad">{error}</Notice>}

      {runs === null ? (
        <div className="flex flex-col gap-4">{[0, 1].map((i) => <Skeleton key={i} className="h-40" />)}</div>
      ) : runs.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 px-6 py-space-2xl text-center">
          <Icon name="description" className="text-[40px] text-outline" />
          <div className="font-headline-sm text-headline-sm text-on-surface">No tailored resumes yet</div>
          <p className="max-w-md font-body-md text-body-md text-on-surface-variant">Paste a job description and get your first one in about a minute.</p>
          <LinkButton to="/new">Tailor your first resume</LinkButton>
        </Card>
      ) : shown.length === 0 ? (
        <Card className="p-6 text-center font-body-md text-body-md text-on-surface-variant">No resumes match “{q}”.</Card>
      ) : (
        <div className="flex flex-col gap-4">
          {shown.map((r) => {
            const delta = r.must_before !== null && r.must_after !== null ? Math.round((r.must_after - r.must_before) * 100) : null
            return (
              <Card key={r.id} className="flex flex-col justify-between gap-4 p-space-lg transition-all hover:shadow-md md:flex-row md:items-center">
                <button type="button" onClick={() => navigate(`/runs/${r.id}`)} className="min-w-0 flex-1 text-left">
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    {r.company && <span className="rounded bg-surface-container px-2.5 py-0.5 font-label-sm text-label-sm font-semibold text-on-surface">{r.company}</span>}
                    <span className="font-body-sm text-body-sm text-on-surface-variant">Tailored {timeAgo(r.created_at)}</span>
                    {r.model && <Badge className="font-code-sm">{r.model}</Badge>}
                  </div>
                  <div className="font-headline-sm text-headline-sm text-on-surface">{r.job_title || 'Tailored resume'}</div>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span className="inline-flex items-center gap-2 rounded-full bg-surface-container-low px-3 py-1.5 font-code-sm text-code-sm text-on-surface">
                      Match: {pct(r.must_before)} <Icon name="arrow_forward" className="text-[14px]" /> <strong className="text-primary-container">{pct(r.must_after)}</strong>
                      {delta !== null && delta !== 0 && <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${delta > 0 ? 'bg-primary-container text-on-primary-container' : 'bg-error-container text-on-error-container'}`}>{delta > 0 ? '+' : ''}{delta}%</span>}
                    </span>
                    {r.health !== null && (
                      <span className="inline-flex items-center gap-1.5 rounded-full bg-surface-container-low px-3 py-1.5 font-label-sm text-label-sm text-on-surface">
                        <Icon name={r.health >= 1 ? 'check_circle' : 'warning'} fill className={`text-[16px] ${r.health >= 1 ? 'text-primary-container' : 'text-amber-600'}`} /> ATS {pct(r.health)}
                      </span>
                    )}
                  </div>
                </button>
                <div className="flex items-center gap-2">
                  <LinkButton to={`/runs/${r.id}`} variant="secondary" size="sm">Open</LinkButton>
                  {r.has_pdf && <IconBtn label="Download PDF" icon="picture_as_pdf" onClick={() => download(r, 'pdf')} />}
                  <IconBtn label="Download .tex" icon="code" onClick={() => download(r, 'tex')} />
                  <IconBtn label="Delete" icon="delete" onClick={() => remove(r)} />
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}

function Chip({ icon, to, children }: { icon: string; to: string; children: React.ReactNode }) {
  return (
    <Link to={to} className="inline-flex items-center gap-1.5 rounded-full bg-surface-container-lowest px-3 py-1.5 font-code-sm text-code-sm text-on-surface shadow-sm transition hover:shadow-md">
      <Icon name={icon} className="text-[16px] text-primary-container" /> {children}
    </Link>
  )
}

function IconBtn({ icon, label, onClick }: { icon: string; label: string; onClick: () => void }) {
  return (
    <Button variant="ghost" size="sm" aria-label={label} title={label} onClick={onClick} className="!px-2.5">
      <Icon name={icon} className="text-[20px]" />
    </Button>
  )
}
