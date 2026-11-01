import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { ErrorNote, SessionStatus, todayISO } from './ui'

function pad(n) {
  return String(n).padStart(2, '0')
}

/** Course + today's session selector, with "open" and "start a session now" shortcuts. */
export function SessionPicker({ value, onChange, requireOpen = true }) {
  const { isAdmin } = useAuth()
  const toast = useToast()
  const [courses, setCourses] = useState([])
  const [courseId, setCourseId] = useState('')
  const [day, setDay] = useState(todayISO())
  const [sessions, setSessions] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    api
      .get('/courses')
      .then((list) => {
        setCourses(list)
        if (list.length && !courseId) setCourseId(String(list[0].course_id))
      })
      .catch(setError)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadSessions = async (keep) => {
    if (!courseId) return
    try {
      const list = await api.get('/sessions', { course_id: courseId, date: day })
      setSessions(list)
      const current = list.find((s) => s.session_id === (keep ?? value?.session_id))
      const pick = current || list.find((s) => s.status === 'OPEN') || null
      onChange(pick)
    } catch (err) {
      setError(err)
    }
  }

  useEffect(() => {
    loadSessions()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, day])

  const selected = useMemo(() => sessions.find((s) => s.session_id === value?.session_id), [sessions, value])

  const openSelected = async (force = false) => {
    if (!selected) return
    setBusy(true)
    try {
      await api.post(`/sessions/${selected.session_id}/open`, { force })
      toast.success(`${selected.course_code} is open for attendance`)
      await loadSessions(selected.session_id)
    } catch (err) {
      if (err.code === 'OUTSIDE_SESSION_WINDOW' && isAdmin) {
        if (window.confirm(`${err.message}. Open it anyway?`)) return openSelected(true)
      } else toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  const startNow = async () => {
    setBusy(true)
    try {
      const now = new Date()
      const end = new Date(now.getTime() + 60 * 60000)
      const endTime = end.getDate() !== now.getDate() ? '23:59' : `${pad(end.getHours())}:${pad(end.getMinutes())}`
      const created = await api.post('/sessions', {
        course_id: Number(courseId),
        session_date: todayISO(),
        start_time: `${pad(now.getHours())}:${pad(now.getMinutes())}`,
        end_time: endTime,
        late_after_min: 10,
        open_now: true,
      })
      setDay(todayISO())
      toast.success('Session started and open for attendance')
      await loadSessions(created.session_id)
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="sheet p-4">
      <div className="grid gap-3 sm:grid-cols-[1.4fr_1fr_1.4fr]">
        <div>
          <label className="label" htmlFor="sp-course">
            Course
          </label>
          <select id="sp-course" className="input" value={courseId} onChange={(e) => setCourseId(e.target.value)}>
            {courses.map((c) => (
              <option key={c.course_id} value={c.course_id}>
                {c.code} {c.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="sp-day">
            Date
          </label>
          <input id="sp-day" type="date" className="input" value={day} onChange={(e) => setDay(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="sp-session">
            Session
          </label>
          <select
            id="sp-session"
            className="input"
            value={value?.session_id || ''}
            onChange={(e) => onChange(sessions.find((s) => s.session_id === Number(e.target.value)) || null)}
          >
            <option value="">{sessions.length ? 'Choose a session' : 'No sessions on this date'}</option>
            {sessions.map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {s.start_time}–{s.end_time} {s.topic ? `(${s.topic})` : ''} [{s.status.toLowerCase()}]
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {selected && <SessionStatus status={selected.status} />}
        {selected && (
          <span className="text-sm text-muted">
            {selected.enrolled} enrolled, {selected.present_count + selected.late_count} marked so far
          </span>
        )}
        <span className="flex-1" />
        {selected?.status === 'SCHEDULED' && (
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => openSelected(false)}>
            Open session
          </button>
        )}
        <button className="btn btn-quiet btn-sm" disabled={busy || !courseId} onClick={startNow}>
          Start a session now
        </button>
      </div>
      {requireOpen && selected && selected.status !== 'OPEN' && (
        <p className="mt-2 text-sm text-late">Attendance can only be taken while the session is open.</p>
      )}
      <ErrorNote error={error} className="mt-3" />
    </div>
  )
}
