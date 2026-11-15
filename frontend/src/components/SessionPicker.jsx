import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { useToast } from '../context/ToastContext'
import { ErrorNote, SessionStatus, hourSlot, isCurrentSlot, slotLabel, todayISO } from './ui'

/** Course + today's session selector, with "open" and "start a lecture now" shortcuts.
 *
 * A lecture is one clock hour and only the one belonging to the hour we are in
 * can be opened, so this is also what gates group attendance, late entry and
 * live recognition: they all need an OPEN session. */
export function SessionPicker({ value, onChange, requireOpen = true }) {
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

  const openSelected = async () => {
    if (!selected) return
    setBusy(true)
    try {
      await api.post(`/sessions/${selected.session_id}/open`, {})
      toast.success(`${selected.course_code} is open for attendance`)
      await loadSessions(selected.session_id)
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  // one click: the lecture for the hour we are in, already open
  const startNow = async () => {
    setBusy(true)
    try {
      const created = await api.post('/sessions/now', { course_id: Number(courseId) })
      setDay(todayISO())
      toast.success(`${created.course_code} is open, ${created.start_time}-${created.end_time}`)
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
        {selected?.status === 'SCHEDULED' &&
          (isCurrentSlot(selected) ? (
            <button className="btn btn-primary btn-sm" disabled={busy} onClick={openSelected}>
              Open session
            </button>
          ) : (
            <span className="text-xs text-muted">Only the {slotLabel(hourSlot().hour)} lecture can be open now</span>
          ))}
        <button className="btn btn-quiet btn-sm" disabled={busy || !courseId} onClick={startNow}>
          Start the {slotLabel(hourSlot().hour)} lecture
        </button>
      </div>
      {requireOpen && selected && selected.status !== 'OPEN' && (
        <p className="mt-2 text-sm text-late">Attendance can only be taken while the session is open.</p>
      )}
      <ErrorNote error={error} className="mt-3" />
    </div>
  )
}
