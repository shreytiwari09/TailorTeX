import { useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { Link, type LinkProps } from 'react-router-dom'

/** Material Symbols icon (font loaded in index.html). */
export function Icon({ name, className = '', fill = false }: { name: string; className?: string; fill?: boolean }) {
  return (
    <span aria-hidden="true" className={`material-symbols-outlined ${fill ? 'fill' : ''} ${className}`}>
      {name}
    </span>
  )
}

export function Logo({ className = '' }: { className?: string }) {
  return (
    <span className={`flex items-center gap-2 ${className}`}>
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-container">
        <Icon name="terminal" className="text-[18px] text-primary-container" />
      </span>
      <span className="font-headline-sm text-headline-sm tracking-tight text-on-surface">
        Tailor<span className="font-code-md text-primary-container">TeX</span>
      </span>
    </span>
  )
}

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
const VARIANT: Record<Variant, string> = {
  primary: 'bg-primary-container text-on-primary-container hover:bg-primary shadow-sm',
  secondary: 'bg-surface-container-lowest text-on-surface border border-outline-variant hover:bg-surface-container-low',
  ghost: 'text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface',
  danger: 'bg-surface-container-lowest text-error border border-outline-variant hover:bg-error-container',
}
const SIZE = { md: 'px-5 py-2.5', sm: 'px-4 py-2', lg: 'px-7 py-3.5' }
const BASE =
  'inline-flex items-center justify-center gap-1.5 rounded-full font-label-md text-label-md font-semibold whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary-container'

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: keyof typeof SIZE; loading?: boolean }

export function Button({ variant = 'primary', size = 'md', loading, className = '', children, disabled, ...rest }: BtnProps) {
  return (
    <button type="button" disabled={disabled || loading} className={`${BASE} ${VARIANT[variant]} ${SIZE[size]} ${className}`} {...rest}>
      {loading && <Spinner />}
      {children}
    </button>
  )
}

export function LinkButton({ variant = 'primary', size = 'md', className = '', ...rest }: LinkProps & { variant?: Variant; size?: keyof typeof SIZE }) {
  return <Link className={`${BASE} ${VARIANT[variant]} ${SIZE[size]} ${className}`} {...rest} />
}

export function Spinner({ className = '' }: { className?: string }) {
  return <span role="status" aria-label="Working" className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent ${className}`} />
}

export function Card({ className = '', children }: { className?: string; children: ReactNode }) {
  return <div className={`rounded-xl border border-outline-variant/60 bg-surface-container-lowest shadow-sm ${className}`}>{children}</div>
}

type Tone = 'neutral' | 'accent' | 'good' | 'warn' | 'bad'
const TONE: Record<Tone, string> = {
  neutral: 'bg-surface-container text-on-surface-variant',
  accent: 'bg-primary-fixed/60 text-primary',
  good: 'bg-emerald-50 text-emerald-700',
  warn: 'bg-amber-50 text-amber-800',
  bad: 'bg-error-container text-on-error-container',
}

export function Badge({ tone = 'neutral', className = '', children }: { tone?: Tone; className?: string; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 font-label-sm text-label-sm ${TONE[tone]} ${className}`}>{children}</span>
  )
}

/** The small "i" that opens a short explanation, so pages don't need paragraphs of help text. */
export function InfoTip({ children, className = '', align = 'center' }: { children: ReactNode; className?: string; align?: 'center' | 'left' | 'right' }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])
  const pos = align === 'left' ? 'left-0' : align === 'right' ? 'right-0' : 'left-1/2 -translate-x-1/2'
  return (
    <span ref={ref} className={`relative inline-flex ${className}`} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" aria-label="More info" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="flex h-5 w-5 items-center justify-center rounded-full text-outline hover:text-on-surface focus-visible:outline-2 focus-visible:outline-primary-container">
        <Icon name="info" className="text-[16px]" />
      </button>
      {open && (
        <span role="tooltip" className={`absolute top-full z-40 mt-1.5 w-64 rounded-lg bg-inverse-surface p-3 text-left font-body-sm text-body-sm font-normal normal-case tracking-normal text-inverse-on-surface shadow-xl ${pos}`}>
          {children}
        </span>
      )}
    </span>
  )
}

export function Field({ label, hint, info, children, className = '' }: { label: string; hint?: string; info?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={`flex flex-col gap-1.5 ${className}`}>
      <span className="flex items-center gap-1 font-label-md text-label-md text-on-surface">
        {label}
        {info && <InfoTip>{info}</InfoTip>}
      </span>
      {children}
      {hint && <span className="font-body-sm text-body-sm text-on-surface-variant">{hint}</span>}
    </label>
  )
}

export const inputClass =
  'w-full rounded-lg border border-outline-variant bg-surface-container-low px-3.5 py-2.5 font-body-md text-body-md text-on-surface placeholder:text-outline transition focus:border-primary-container focus:bg-surface-container-lowest focus:outline-none focus:ring-4 focus:ring-primary-container/10'

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${inputClass} ${props.className ?? ''}`} />
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`${inputClass} resize-y ${props.className ?? ''}`} />
}

export function Notice({ tone = 'neutral', icon, children, className = '' }: { tone?: Tone; icon?: string; children: ReactNode; className?: string }) {
  const icons: Record<Tone, string> = { neutral: 'info', accent: 'info', good: 'check_circle', warn: 'warning', bad: 'error' }
  return (
    <div role={tone === 'bad' ? 'alert' : undefined} className={`flex items-start gap-2 rounded-lg px-3.5 py-2.5 font-body-sm text-body-sm ${TONE[tone]} ${className}`}>
      <Icon name={icon ?? icons[tone]} className="mt-0.5 text-[18px]" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

export function Avatar({ name, url, size = 32 }: { name?: string; url?: string | null; size?: number }) {
  const initials = (name || '?').split(/\s+/).map((w) => w[0]).filter(Boolean).slice(0, 2).join('').toUpperCase()
  if (url) return <img src={url} alt="" referrerPolicy="no-referrer" style={{ width: size, height: size }} className="rounded-full object-cover" />
  return (
    <span style={{ width: size, height: size }} className="flex items-center justify-center rounded-full bg-primary font-label-sm text-label-sm text-on-primary">
      {initials}
    </span>
  )
}

export function PageTitle({ eyebrow, title, info, actions, children }: { eyebrow?: ReactNode; title: string; info?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-2 font-label-sm text-label-sm uppercase tracking-wider text-primary-container">{eyebrow}</div>}
        <h1 className="flex items-center gap-2 font-headline-lg-mobile text-headline-lg-mobile tracking-tight text-on-surface md:font-headline-lg md:text-headline-lg">
          {title}
          {info && <InfoTip align="left">{info}</InfoTip>}
        </h1>
        {children}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-surface-container ${className}`} />
}
