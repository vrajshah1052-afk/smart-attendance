import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { useToast } from '../context/ToastContext'
import { ErrorNote, SLOTS, SessionStatus, hourSlot, slotLabel, todayISO } from './ui'

/** Course + date + lecture-slot selector for taking attendance.
 *
 * The day is a timetable of twenty-four one-hour slots, the same list the New
 * session form offers, so a slot with no lecture yet is still something you can
 * point at. Only the slot belonging to the hour we are in can be started or
 * opened, which is what gates group attendance, late entry and live
 * recognition: all three need a session that is OPEN.
 */
export function SessionPicker({ value, onChange, requireOpen = true }) {
  const toast = useToast()
  const [courses, setCourses] = useState([])
  const [courseId, setCourseId] = useState('')
  const [day, setDay] = useState(todayISO())
  const [sessions, setSessions] = useState([])
  const [hour, setHour] = useState(hourSlot().hour)
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

  const hourOf = (session) => Number(String(session.start_time).slice(0, 2))

  const loadSessions = async (preferHour) => {
    if (!courseId) return
    try {
      const list = await api.get('/sessions', { course_id: courseId, date: day })
      setSessions(list)
      // land on the lecture that is running, else the slot the user was on
      const open = list.find((s) => s.status === 'OPEN')
      const next = preferHour ?? (open ? hourOf(open) : hour)
      setHour(next)
      onChange(list.find((s) => hourOf(s) === next) || null)
    } catch (err) {
      setError(err)
    }
  }

  useEffect(() => {
    loadSessions()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId, day])

  const byHour = useMemo(() => {
    const map = {}
    sessions.forEach((s) => {
      map[hourOf(s)] = s
    })
    return map
  }, [sessions])

  const selected = byHour[hour] || null
  const isToday = day === todayISO()
  const nowHour = hourSlot().hour
  const thisSlotIsNow = isToday && hour === nowHour

  const pickHour = (h) => {
    setHour(h)
    onChange(byHour[h] || null)
  }

  const openSelected = async () => {
    if (!selected) return
    setBusy(true)
    try {
      await api.post(`/sessions/${selected.session_id}/open`, {})
      toast.success(`${selected.course_code} is open for attendance`)
      await loadSessions(hour)
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  // one click: the lecture for the hour we are in, created if it does not exist
  const startNow = async () => {
    setBusy(true)
    try {
      const created = await api.post('/sessions/now', { course_id: Number(courseId) })
      setDay(todayISO())
      toast.success(`${created.course_code} is open, ${created.start_time}-${created.end_time}`)
      await loadSessions(nowHour)
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
            Lecture slot
          </label>
          <select id="sp-session" className="input" value={hour} onChange={(e) => pickHour(Number(e.target.value))}>
            {SLOTS.map((s) => {
              const session = byHour[s.hour]
              const marks = [
                session ? session.status.toLowerCase() : 'no lecture',
                isToday && s.hour === nowHour ? 'now' : null,
              ].filter(Boolean)
              return (
                <option key={s.hour} value={s.hour}>
                  {s.start} - {s.end} · {marks.join(', ')}
                  {session?.topic ? ` · ${session.topic}` : ''}
                </option>
              )
            })}
          </select>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {selected ? (
          <>
            <SessionStatus status={selected.status} />
            <span className="text-sm text-muted">
              {selected.enrolled} enrolled, {selected.present_count + selected.late_count} marked so far
            </span>
          </>
        ) : (
          <span className="text-sm text-muted">
            No lecture in the {slotLabel(hour)} slot{isToday ? '' : ` on ${day}`}.
          </span>
        )}
        <span className="flex-1" />
        {thisSlotIsNow ? (
          selected ? (
            selected.status === 'SCHEDULED' && (
              <button className="btn btn-primary btn-sm" disabled={busy} onClick={openSelected}>
                Open this lecture
              </button>
            )
          ) : (
            <button className="btn btn-primary btn-sm" disabled={busy || !courseId} onClick={startNow}>
              Start the {slotLabel(nowHour)} lecture
            </button>
          )
        ) : (
          <>
            <span className="text-xs text-muted">Only the {slotLabel(nowHour)} lecture can run right now</span>
            <button
              className="btn btn-quiet btn-sm"
              disabled={busy}
              onClick={() => {
                setDay(todayISO())
                pickHour(nowHour)
              }}
            >
              Go to {slotLabel(nowHour)}
            </button>
          </>
        )}
      </div>

      {requireOpen && selected && selected.status !== 'OPEN' && (
        <p className="mt-2 text-sm text-late">Attendance can only be taken while the lecture is open.</p>
      )}
      <ErrorNote error={error} className="mt-3" />
    </div>
  )
}
