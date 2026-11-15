import { useEffect, useId, useRef } from 'react'
import { Loader2, X } from 'lucide-react'

export function PageHeader({ title, description, actions, eyebrow }) {
  return (
    <div className="mb-7 flex animate-fade-up flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="max-w-prose">
        {eyebrow && <p className="eyebrow mb-2">{eyebrow}</p>}
        <h1 className="text-gradient pb-1 text-[28px] font-bold sm:text-[34px]">{title}</h1>
        {description && <p className="mt-1.5 text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

export function Spinner({ label = 'Loading', className = '' }) {
  return (
    <span className={`inline-flex items-center gap-2 text-sm text-muted ${className}`} role="status">
      <Loader2 size={16} className="animate-spin" /> {label}
    </span>
  )
}

export function Empty({ title, children, action }) {
  return (
    <div className="flex flex-col items-start gap-2 px-5 py-8">
      <p className="font-bold">{title}</p>
      {children && <p className="max-w-prose text-sm text-muted">{children}</p>}
      {action}
    </div>
  )
}

export function ErrorNote({ error, className = '' }) {
  if (!error) return null
  const message = typeof error === 'string' ? error : error.message
  return (
    <div role="alert" className={`rounded-xl border border-absent/40 bg-absent/10 px-3.5 py-2.5 text-sm text-fg ${className}`}>
      {message}
    </div>
  )
}

export function Field({ label, hint, children, error }) {
  const id = useId()
  const child = typeof children === 'function' ? children(id) : children
  return (
    <div>
      {label && (
        <label className="label" htmlFor={id}>
          {label}
        </label>
      )}
      {child}
      {error ? <p className="mt-1 text-xs text-absent">{error}</p> : hint && <p className="hint">{hint}</p>}
    </div>
  )
}

const TONE = {
  ink: 'border-ink/30 bg-ink/10 text-ink',
  late: 'border-late/35 bg-late/10 text-late',
  absent: 'border-absent/35 bg-absent/10 text-absent',
  spoof: 'border-spoof/35 bg-spoof/10 text-spoof',
  muted: 'border-line bg-panel2/60 text-muted',
}

export function Chip({ tone = 'muted', children, title }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-semibold ${TONE[tone]}`}>
      {children}
    </span>
  )
}

const SESSION_TONE = { OPEN: 'ink', SCHEDULED: 'muted', CLOSED: 'muted', CANCELLED: 'absent' }
const SESSION_TEXT = { OPEN: 'Open', SCHEDULED: 'Scheduled', CLOSED: 'Closed', CANCELLED: 'Cancelled' }
export function SessionStatus({ status }) {
  return <Chip tone={SESSION_TONE[status] || 'muted'}>{SESSION_TEXT[status] || status}</Chip>
}

const FACE_TONE = { ENROLLED: 'ink', PENDING: 'late', PENDING_APPROVAL: 'late', REENROLL_REQUIRED: 'absent' }
const FACE_TEXT = {
  ENROLLED: 'Face enrolled',
  PENDING: 'No face yet',
  PENDING_APPROVAL: 'Waiting for approval',
  REENROLL_REQUIRED: 'Re-enrol face',
}
export function FaceStatus({ status }) {
  return <Chip tone={FACE_TONE[status] || 'muted'}>{FACE_TEXT[status] || status}</Chip>
}

/** The handwritten register mark: P (blue ink), L (amber), A (red ink). */
const MARKS = {
  PRESENT: { letter: 'P', cls: 'text-ink', word: 'Present' },
  LATE: { letter: 'L', cls: 'text-late', word: 'Late' },
  ABSENT: { letter: 'A', cls: 'text-absent', word: 'Absent' },
}
export function Mark({ status, size = 22, animate = false, delay = 0 }) {
  const m = MARKS[status]
  if (!m) return <span className="text-muted" aria-label="Not marked">–</span>
  return (
    <span
      className={`mark ${m.cls} ${animate ? 'mark-ink-in' : ''}`}
      style={{ fontSize: size, animationDelay: animate ? `${delay}ms` : undefined }}
      title={m.word}
      aria-label={m.word}
    >
      {m.letter}
    </span>
  )
}

export function Pct({ value, threshold = 75 }) {
  if (value === null || value === undefined) return <span className="text-muted">–</span>
  const low = value < threshold
  return <span className={`tnum font-bold ${low ? 'text-absent' : ''}`}>{Number(value).toFixed(1)}%</span>
}

export function Bar({ value, threshold = 75 }) {
  const v = Math.max(0, Math.min(100, Number(value) || 0))
  return (
    <div className="relative h-2 w-full rounded-full bg-panel2" aria-hidden="true">
      <div
        className={`h-2 rounded-full bg-gradient-to-r ${v < threshold ? 'from-glow3 to-absent' : 'from-glow1 via-ink to-glow2'}`}
        style={{ width: `${v}%` }}
      />
      <div className="absolute -top-1 h-4 w-px bg-fg/40" style={{ left: `${threshold}%` }} title={`${threshold}% required`} />
    </div>
  )
}

export function Modal({ open, title, onClose, children, footer, wide = false }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => e.key === 'Escape' && onClose?.()
    document.addEventListener('keydown', onKey)
    ref.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-bg/60 p-0 backdrop-blur-sm sm:items-center sm:p-6" onMouseDown={onClose}>
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`glow-border max-h-[92vh] w-full animate-fade-up overflow-y-auto rounded-t-2xl border border-line/60 bg-panel shadow-2xl outline-none sm:rounded-2xl ${wide ? 'sm:max-w-3xl' : 'sm:max-w-lg'}`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line/70 px-5 py-3.5">
          <h2 className="text-lg">{title}</h2>
          <button className="rounded-lg p-1 text-muted hover:bg-panel2 hover:text-fg" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line/70 px-5 py-3.5">{footer}</div>}
      </div>
    </div>
  )
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="glass mb-6 flex w-full gap-1 overflow-x-auto rounded-2xl border border-line/70 p-1 sm:w-fit" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.value}
          role="tab"
          aria-selected={value === t.value}
          onClick={() => onChange(t.value)}
          className={`whitespace-nowrap rounded-xl px-3.5 py-1.5 text-sm font-semibold transition-all ${
            value === t.value
              ? 'bg-gradient-to-r from-glow1 to-ink text-white shadow-[0_6px_18px_-8px_rgb(var(--glow1))]'
              : 'text-muted hover:bg-panel2/70 hover:text-fg'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

const LEDGER_TONE = { ink: 'text-ink', late: 'text-late', absent: 'text-absent', spoof: 'text-spoof' }
const LEDGER_ACCENT = {
  ink: 'from-glow1 to-ink',
  late: 'from-late to-glow3',
  absent: 'from-glow3 to-absent',
  spoof: 'from-spoof to-glow1',
}

/** Key figures as glass tiles, each with a coloured accent line. */
export function Ledger({ items }) {
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4 2xl:grid-cols-7">
      {items.map((it, i) => (
        <div
          key={it.label}
          className="sheet group relative min-w-0 animate-fade-up overflow-hidden px-4 py-3.5 transition-transform duration-300 hover:-translate-y-0.5"
          style={{ animationDelay: `${i * 45}ms` }}
        >
          <span
            className={`absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r ${LEDGER_ACCENT[it.tone] || 'from-glow1 via-glow2 to-glow3'} opacity-80`}
            aria-hidden="true"
          />
          <span className="absolute -right-6 -top-8 h-20 w-20 rounded-full bg-ink/10 blur-2xl transition-opacity group-hover:opacity-100" aria-hidden="true" />
          <dt className="eyebrow leading-snug">{it.label}</dt>
          <dd className={`tnum mt-1.5 font-display text-[26px] font-bold leading-none ${LEDGER_TONE[it.tone] || 'text-fg'}`}>
            {it.value ?? '–'}
          </dd>
        </div>
      ))}
    </dl>
  )
}

export function fmtDate(value) {
  if (!value) return '–'
  const d = new Date(value.length === 10 ? `${value}T00:00:00` : value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function fmtDateTime(value) {
  if (!value) return '–'
  const d = new Date(value)
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

const pad2 = (n) => String(n).padStart(2, '0')

/** The one-hour slot an hour covers: 9 -> { start: '09:00', end: '10:00' }. */
export function slotOf(hour) {
  return { hour, start: `${pad2(hour)}:00`, end: hour === 23 ? '23:59' : `${pad2(hour + 1)}:00` }
}

/** The slot the clock is in right now: 09:06 -> { start: '09:00', end: '10:00' }. */
export function hourSlot(date = new Date()) {
  return slotOf(date.getHours())
}

/** Every lecture slot of the day, 00:00-01:00 through 23:00-23:59. */
export const SLOTS = Array.from({ length: 24 }, (_, h) => slotOf(h))

export function slotLabel(hour) {
  const s = slotOf(hour)
  return `${s.start} - ${s.end}`
}

/** True when this session is the lecture belonging to the hour we are in. */
export function isCurrentSlot(session) {
  if (!session) return false
  const now = new Date()
  return session.session_date === todayISO(now) && Number(String(session.start_time).slice(0, 2)) === now.getHours()
}

export function todayISO(date = new Date()) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`
}
