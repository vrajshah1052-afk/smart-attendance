import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { BookOpen, Copy, Maximize2, QrCode, RefreshCw, Users, X } from 'lucide-react'
import { api } from '../api/client'
import { Chip, Empty, ErrorNote, Modal, PageHeader, Pct, Spinner } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { useApi } from '../hooks/useApi'

// Projector view: big QR + class code for the whole room to scan (portal: above the app shell).
function Present({ poster, onClose }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  const c = poster.course
  return createPortal(
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-6 overflow-y-auto bg-bg/95 p-6 text-center backdrop-blur-xl">
      <button className="btn btn-quiet absolute right-5 top-5" onClick={onClose}>
        <X size={17} /> Close
      </button>
      <p className="eyebrow">Scan to join</p>
      <h1 className="max-w-4xl text-[34px] font-bold leading-tight sm:text-[52px]">
        <span className="text-gradient">{c.name}</span>
      </h1>
      <div className="relative">
        <div className="absolute -inset-6 rounded-[40px] bg-gradient-to-br from-glow1/50 via-ink/30 to-glow2/50 blur-2xl" aria-hidden="true" />
        <img src={poster.qr_png} alt={`QR code to join ${c.code}`} className="relative w-[min(70vw,420px)] rounded-3xl bg-white p-4" />
      </div>
      <div>
        <p className="eyebrow">or open {new URL(poster.url).host}/join and type</p>
        <p className="mt-2 font-display text-[56px] font-bold tracking-[0.3em] text-ink sm:text-[84px]">{poster.join_code}</p>
      </div>
      {!poster.join_open && <Chip tone="absent">Joining is closed</Chip>}
    </div>,
    document.body,
  )
}

function JoinPoster({ course, onClose, onChanged }) {
  const toast = useToast()
  const [poster, setPoster] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [presenting, setPresenting] = useState(false)

  useEffect(() => {
    if (!course) return
    setPoster(null)
    setError(null)
    api.get(`/courses/${course.course_id}/join`).then(setPoster).catch(setError)
  }, [course])

  const change = async (request, message) => {
    setBusy(true)
    setError(null)
    try {
      setPoster(await request())
      toast.success(message)
      onChanged()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const reset = () =>
    window.confirm('Make a new class code? The current QR and code stop working.') &&
    change(() => api.post(`/courses/${course.course_id}/join/reset`), 'New class code ready')
  const toggle = () =>
    change(() => api.put(`/courses/${course.course_id}/join`, { open: !poster.join_open }), poster.join_open ? 'Joining closed' : 'Joining open')

  return (
    <>
      <Modal open={!!course} title={`Class code for ${course?.code}`} onClose={onClose} wide>
        {!poster && !error && <Spinner />}
        <ErrorNote error={error} className="mb-3" />
        {poster && (
          <div className="grid items-center gap-6 sm:grid-cols-[auto_1fr]">
            <img src={poster.qr_png} alt={`QR code to join ${poster.course.code}`} className="mx-auto w-60 rounded-2xl bg-white p-2" />
            <div>
              <p className="eyebrow">Class code</p>
              <p className="font-display text-5xl font-bold tracking-[0.25em] text-ink">{poster.join_code}</p>
              <p className="mt-3 text-sm text-muted">
                Students scan the QR with their phone camera. Existing students sign in and join; new students create
                their account there with a few selfies.
              </p>
              <div className="mt-3 flex items-center gap-2 rounded-xl border border-line/70 bg-panel2/60 px-3 py-2 text-xs">
                <span className="truncate">{poster.url}</span>
                <button
                  className="ml-auto shrink-0 text-ink hover:underline"
                  onClick={() => navigator.clipboard?.writeText(poster.url).then(() => toast.success('Link copied'))}
                >
                  <Copy size={14} className="inline" /> Copy
                </button>
              </div>
              <p className="mt-3 flex items-center gap-2 text-sm">
                <Users size={15} className="text-ink" /> {poster.course.enrolled} enrolled
                <Chip tone={poster.join_open ? 'ink' : 'absent'}>{poster.join_open ? 'Joining open' : 'Joining closed'}</Chip>
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button className="btn btn-primary" onClick={() => setPresenting(true)}>
                  <Maximize2 size={16} /> Show to class
                </button>
                <button className="btn btn-quiet" disabled={busy} onClick={toggle}>
                  {poster.join_open ? 'Close joining' : 'Open joining'}
                </button>
                <button className="btn btn-quiet" disabled={busy} onClick={reset}>
                  <RefreshCw size={15} /> New code
                </button>
              </div>
            </div>
          </div>
        )}
      </Modal>
      {presenting && poster && <Present poster={poster} onClose={() => setPresenting(false)} />}
    </>
  )
}

export default function Courses() {
  const courses = useApi(() => api.get('/courses'), [])
  const [posterFor, setPosterFor] = useState(null)

  return (
    <>
      <PageHeader
        eyebrow="Class codes"
        title="Courses"
        description="Every course has a QR code and a 6-character class code. Show it in class: students scan it to join, and new students sign up with their face on the spot."
      />
      <ErrorNote error={courses.error} className="mb-4" />
      {courses.loading && !courses.data ? (
        <Spinner />
      ) : !courses.data?.length ? (
        <Empty title="No courses yet">An admin creates courses through the API (POST /courses).</Empty>
      ) : (
        <ul className="grid gap-5 md:grid-cols-2 2xl:grid-cols-3">
          {courses.data.map((c, i) => (
            <li key={c.course_id} className="sheet group relative flex animate-fade-up flex-col overflow-hidden p-5" style={{ animationDelay: `${i * 50}ms` }}>
              <div className="absolute -right-12 -top-16 h-40 w-40 rounded-full bg-glow1/15 blur-2xl transition-opacity group-hover:opacity-100" aria-hidden="true" />
              <div className="relative flex items-start justify-between gap-3">
                <div>
                  <p className="eyebrow">
                    {c.branch} · Year {c.year_of_study} · Sem {c.semester}
                  </p>
                  <h2 className="mt-1 text-lg font-bold leading-snug">{c.name}</h2>
                  <p className="text-sm text-muted">{c.coordinator || 'No coordinator'}</p>
                </div>
                <Chip tone="ink">
                  <BookOpen size={13} /> {c.code}
                </Chip>
              </div>
              <dl className="relative mt-5 grid grid-cols-3 gap-2 text-center">
                {[
                  ['Enrolled', c.enrolled],
                  ['Lectures', c.sessions_held],
                  ['Average', c.avg_attendance_pct != null ? <Pct value={c.avg_attendance_pct} /> : '–'],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-xl border border-line/60 bg-panel2/50 px-2 py-2">
                    <dt className="text-[11px] uppercase tracking-wide text-muted">{label}</dt>
                    <dd className="font-display text-lg font-bold">{value}</dd>
                  </div>
                ))}
              </dl>
              <div className="relative mt-auto pt-5">
                <button className="btn btn-primary w-full" onClick={() => setPosterFor(c)}>
                  <QrCode size={16} /> Class code and QR
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <JoinPoster course={posterFor} onClose={() => setPosterFor(null)} onChanged={courses.reload} />
    </>
  )
}
