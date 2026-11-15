import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Empty, ErrorNote, Field, Mark, Modal, PageHeader, SessionStatus, Spinner, fmtDate, hourSlot, todayISO } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { useApi } from '../hooks/useApi'

function QrModal({ session, onClose }) {
  const [qr, setQr] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    if (!session) return undefined
    let timer
    const load = async () => {
      try {
        const data = await api.get(`/sessions/${session.session_id}/qr`)
        setQr(data)
        timer = setTimeout(load, Math.max(2, data.expires_in) * 1000)
      } catch (err) {
        setError(err)
      }
    }
    load()
    return () => clearTimeout(timer)
  }, [session])
  return (
    <Modal open={!!session} title={`Attendance code for ${session?.course_code}`} onClose={onClose}>
      <p className="text-sm text-muted">
        For students whose face is not recognised. They scan the code with their phone or type the six digits under
        Mark with attendance code. The code changes every 30 seconds.
      </p>
      <ErrorNote error={error} className="mt-3" />
      {qr && (
        <div className="mt-4 flex flex-col items-center gap-3">
          <img src={qr.qr_png} alt="Rotating attendance QR code" className="w-64 max-w-full rounded bg-white p-2" />
          <p className="tnum text-4xl font-bold tracking-[0.25em]">{qr.code}</p>
          <p className="text-xs text-muted">Session {session.session_id}, refreshes in {qr.expires_in}s</p>
        </div>
      )}
    </Modal>
  )
}

function RosterModal({ session, onClose }) {
  const roster = useApi(() => (session ? api.get(`/attendance/session/${session.session_id}`) : Promise.resolve(null)), [session?.session_id])
  return (
    <Modal open={!!session} title={`${session?.course_code} on ${fmtDate(session?.session_date)}`} onClose={onClose} wide>
      {roster.loading ? (
        <Spinner />
      ) : (
        <table className="register">
          <thead>
            <tr>
              <th className="roll">Roll</th>
              <th>Student</th>
              <th>How</th>
              <th className="text-center">Mark</th>
            </tr>
          </thead>
          <tbody>
            {roster.data?.students.map((s) => (
              <tr key={s.prn}>
                <td className="roll">{s.division}-{s.roll_no}</td>
                <td>
                  {s.full_name} <span className="text-xs text-muted">{s.prn}</span>
                </td>
                <td className="text-xs text-muted">
                  {s.method ? s.method.toLowerCase().replace('_', ' ') : ''}
                  {s.late_minutes ? `, ${s.late_minutes} min late` : ''}
                </td>
                <td className="text-center">
                  <Mark status={s.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Modal>
  )
}

// a new lecture defaults to the hour you are in, so 08:43 offers 08:00-09:00
const blank = () => {
  const { start, end } = hourSlot()
  return { course_id: '', session_date: todayISO(), start_time: start, end_time: end, late_after_min: 10, room: '', topic: '', open_now: false }
}

export default function Sessions() {
  const toast = useToast()
  const { isAdmin } = useAuth()
  const [filters, setFilters] = useState({ course_id: '', date: todayISO() })
  const courses = useApi(() => api.get('/courses'), [])
  const sessions = useApi(() => api.get('/sessions', filters), [filters.course_id, filters.date])
  const [form, setForm] = useState(null)
  const [qrFor, setQrFor] = useState(null)
  const [rosterFor, setRosterFor] = useState(null)
  const [error, setError] = useState(null)

  const act = async (fn, okMessage) => {
    try {
      await fn()
      if (okMessage) toast.success(okMessage)
      sessions.reload()
    } catch (err) {
      toast.error(err)
    }
  }

  const openSession = (s, force = false) =>
    act(() => api.post(`/sessions/${s.session_id}/open`, { force }), `${s.course_code} is open`).catch(() => {})

  const tryOpen = async (s) => {
    try {
      await api.post(`/sessions/${s.session_id}/open`, { force: false })
      toast.success(`${s.course_code} is open`)
      sessions.reload()
    } catch (err) {
      if (err.code === 'OUTSIDE_SESSION_WINDOW' && isAdmin && window.confirm(`${err.message}. Open anyway?`)) openSession(s, true)
      else toast.error(err)
    }
  }

  // one click: a session for the clock hour we are in, already open
  const startNow = async () => {
    const course_id = Number(filters.course_id || courses.data?.[0]?.course_id)
    if (!course_id) return
    const name = courses.data?.find((c) => c.course_id === course_id)?.code || 'this course'
    const { start, end } = hourSlot()
    if (!window.confirm(`Start ${name} now? It is recorded as the ${start}-${end} lecture.`)) return
    try {
      const s = await api.post('/sessions/now', { course_id })
      toast.success(`${s.course_code} is open, ${s.start_time}-${s.end_time}`)
      sessions.reload()
      setQrFor(s)
    } catch (err) {
      toast.error(err)
    }
  }

  const createSession = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      await api.post('/sessions', { ...form, course_id: Number(form.course_id), late_after_min: Number(form.late_after_min), room: form.room || null, topic: form.topic || null })
      toast.success('Session created')
      setForm(null)
      sessions.reload()
    } catch (err) {
      setError(err)
    }
  }

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  return (
    <>
      <PageHeader
        title="Sessions"
        description="Each lecture is a session. Attendance can only be marked while it is open; closing it marks everyone else absent."
        actions={
          <>
            <button className="btn btn-primary" onClick={startNow} disabled={!courses.data?.length}>
              Start a lecture now
            </button>
            <button className="btn btn-quiet" onClick={() => setForm({ ...blank(), course_id: filters.course_id || courses.data?.[0]?.course_id || '' })}>
              New session
            </button>
          </>
        }
      />
      <div className="mb-4 flex flex-wrap gap-3">
        <select className="input w-auto" value={filters.course_id} onChange={(e) => setFilters((f) => ({ ...f, course_id: e.target.value }))} aria-label="Course">
          <option value="">All courses</option>
          {courses.data?.map((c) => (
            <option key={c.course_id} value={c.course_id}>
              {c.code} {c.name}
            </option>
          ))}
        </select>
        <input type="date" className="input w-auto" value={filters.date} onChange={(e) => setFilters((f) => ({ ...f, date: e.target.value }))} aria-label="Date" />
        <button className="btn btn-quiet" onClick={() => setFilters((f) => ({ ...f, date: '' }))}>
          All dates
        </button>
      </div>
      <ErrorNote error={sessions.error} className="mb-3" />
      <div className="sheet overflow-x-auto">
        {sessions.loading ? (
          <Spinner className="p-4" />
        ) : !sessions.data?.length ? (
          <Empty title="No sessions match these filters">Create one with New session, or pick another date.</Empty>
        ) : (
          <table className="register min-w-[760px]">
            <thead>
              <tr>
                <th>Date</th>
                <th>Time</th>
                <th>Course</th>
                <th>Status</th>
                <th className="text-right">Present</th>
                <th className="text-right">Late</th>
                <th className="text-right">Absent</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sessions.data.map((s) => (
                <tr key={s.session_id}>
                  <td className="whitespace-nowrap">{fmtDate(s.session_date)}</td>
                  <td className="tnum whitespace-nowrap">
                    {s.start_time}–{s.end_time}
                  </td>
                  <td>
                    <span className="font-bold">{s.course_code}</span> {s.topic && <span className="text-muted">{s.topic}</span>}
                    <div className="text-xs text-muted">
                      {s.room || 'No room'}, grace {s.late_after_min} min
                    </div>
                  </td>
                  <td>
                    <SessionStatus status={s.status} />
                  </td>
                  <td className="tnum text-right text-ink">{s.present_count}</td>
                  <td className="tnum text-right text-late">{s.late_count}</td>
                  <td className="tnum text-right text-absent">{s.absent_count}</td>
                  <td>
                    <div className="flex justify-end gap-1.5">
                      {s.status === 'SCHEDULED' && (
                        <>
                          <button className="btn btn-primary btn-sm" onClick={() => tryOpen(s)}>
                            Open
                          </button>
                          <button className="btn btn-quiet btn-sm" onClick={() => window.confirm('Cancel this session?') && act(() => api.post(`/sessions/${s.session_id}/cancel`), 'Session cancelled')}>
                            Cancel
                          </button>
                        </>
                      )}
                      {s.status === 'OPEN' && (
                        <>
                          <button className="btn btn-quiet btn-sm" onClick={() => setQrFor(s)}>
                            Attendance code
                          </button>
                          <button
                            className="btn btn-danger btn-sm"
                            onClick={() =>
                              window.confirm('Close this session? Students without a mark become absent.') &&
                              act(() => api.post(`/sessions/${s.session_id}/close`), 'Session closed')
                            }
                          >
                            Close
                          </button>
                        </>
                      )}
                      <button className="btn btn-quiet btn-sm" onClick={() => setRosterFor(s)}>
                        Register
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <QrModal session={qrFor} onClose={() => setQrFor(null)} />
      <RosterModal session={rosterFor} onClose={() => setRosterFor(null)} />
      <Modal
        open={!!form}
        title="New session"
        onClose={() => setForm(null)}
        footer={
          <>
            <button className="btn btn-quiet" onClick={() => setForm(null)}>
              Cancel
            </button>
            <button className="btn btn-primary" form="session-form">
              Create session
            </button>
          </>
        }
      >
        {form && (
          <form id="session-form" onSubmit={createSession} className="grid gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Field label="Course">
                {(id) => (
                  <select id={id} className="input" required value={form.course_id} onChange={set('course_id')}>
                    {courses.data?.map((c) => (
                      <option key={c.course_id} value={c.course_id}>
                        {c.code} {c.name}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            </div>
            <Field label="Date">{(id) => <input id={id} type="date" className="input" required value={form.session_date} onChange={set('session_date')} />}</Field>
            <Field label="Late after (minutes)" hint="Grace period before a student counts as late">
              {(id) => <input id={id} type="number" min="0" max="60" className="input" value={form.late_after_min} onChange={set('late_after_min')} />}
            </Field>
            <Field label="Starts">{(id) => <input id={id} type="time" className="input" required value={form.start_time} onChange={set('start_time')} />}</Field>
            <Field label="Ends">{(id) => <input id={id} type="time" className="input" required value={form.end_time} onChange={set('end_time')} />}</Field>
            <Field label="Room">{(id) => <input id={id} className="input" maxLength={20} value={form.room} onChange={set('room')} />}</Field>
            <Field label="Topic">{(id) => <input id={id} className="input" maxLength={200} value={form.topic} onChange={set('topic')} />}</Field>
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input type="checkbox" checked={form.open_now} onChange={set('open_now')} className="h-4 w-4 accent-[rgb(var(--ink))]" />
              Open for attendance straight away
            </label>
            <ErrorNote error={error} className="sm:col-span-2" />
          </form>
        )}
      </Modal>
    </>
  )
}
