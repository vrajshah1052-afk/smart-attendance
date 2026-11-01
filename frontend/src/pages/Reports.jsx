import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, downloadFile } from '../api/client'
import { Bar, Empty, ErrorNote, Mark, PageHeader, Pct, SessionStatus, Spinner, Tabs, fmtDate, fmtDateTime, todayISO } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'

function ExportButtons({ query }) {
  const toast = useToast()
  const go = (type) => downloadFile('/reports/export', { ...query, type }, `report.${type}`).catch(toast.error)
  return (
    <div className="flex flex-wrap gap-2">
      <button className="btn btn-quiet btn-sm" onClick={() => go('csv')}>
        Export CSV
      </button>
      <button className="btn btn-quiet btn-sm" onClick={() => go('xlsx')}>
        Export Excel
      </button>
      <button className="btn btn-quiet btn-sm" onClick={() => go('pdf')}>
        Export PDF
      </button>
    </div>
  )
}

export function StudentReport({ data, threshold = 75 }) {
  const s = data.summary
  return (
    <div className="space-y-6">
      <div className="sheet grid gap-4 p-5 sm:grid-cols-[auto_1fr] sm:items-center">
        <div className="sm:border-r sm:border-line sm:pr-8">
          <p className={`tnum text-5xl font-bold ${s.is_shortage ? 'text-absent' : 'text-ink'}`}>
            {s.attendance_pct != null ? `${Number(s.attendance_pct).toFixed(1)}%` : '–'}
          </p>
          <p className="text-sm text-muted">overall attendance</p>
        </div>
        <div className="text-sm">
          <p className="text-lg font-bold">{s.full_name}</p>
          <p className="text-muted">
            {s.prn}, {s.branch} year {s.year_of_study} division {s.division}, roll {s.roll_no}
          </p>
          <p className="mt-2">
            {s.present_count} present, {s.late_count} late and {s.absent_count} absent out of {s.total_sessions} lectures held.
            {s.is_shortage && <span className="font-bold text-absent"> Below the {threshold}% requirement.</span>}
          </p>
        </div>
      </div>

      <section>
        <h3 className="mb-2 text-base">By course</h3>
        <div className="sheet divide-y divide-line">
          {data.courses.map((c) => (
            <div key={c.course_id} className="grid gap-2 px-4 py-3 sm:grid-cols-[1.4fr_2fr_auto] sm:items-center">
              <div>
                <span className="font-bold">{c.course_code}</span> <span className="text-muted">{c.course_name}</span>
              </div>
              <Bar value={c.attendance_pct ?? 0} threshold={threshold} />
              <div className="tnum text-right text-sm">
                <Pct value={c.attendance_pct} threshold={threshold} />{' '}
                <span className="text-muted">
                  ({c.present_count + c.late_count}/{c.sessions_held})
                </span>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-base">Lecture by lecture</h3>
        <div className="sheet max-h-[480px] overflow-auto">
          <table className="register min-w-[560px]">
            <thead className="sticky top-0 bg-panel">
              <tr>
                <th>Date</th>
                <th>Course</th>
                <th>How</th>
                <th className="text-center">Mark</th>
              </tr>
            </thead>
            <tbody>
              {data.history.map((h) => (
                <tr key={h.session_id}>
                  <td className="whitespace-nowrap">
                    {fmtDate(h.session_date)} <span className="tnum text-muted">{h.start_time}</span>
                  </td>
                  <td>{h.course_code}</td>
                  <td className="text-xs text-muted">
                    {h.method ? h.method.toLowerCase().replace('_', ' ') : h.session_status === 'OPEN' ? 'lecture in progress' : ''}
                    {h.late_minutes ? `, ${h.late_minutes} min late` : ''}
                  </td>
                  <td className="text-center">
                    <Mark status={h.status || (h.session_status === 'CLOSED' ? 'ABSENT' : null)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function StudentTab({ initialPrn, threshold }) {
  const [prn, setPrn] = useState(initialPrn || '')
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const load = async (value) => {
    if (!value) return
    setLoading(true)
    setError(null)
    try {
      setData(await api.get(`/attendance/student/${value.trim().toUpperCase()}`))
    } catch (err) {
      setData(null)
      setError(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (initialPrn) load(initialPrn)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPrn])

  return (
    <>
      <form
        className="mb-5 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          load(prn)
        }}
      >
        <input className="input max-w-xs uppercase" placeholder="PRN" value={prn} onChange={(e) => setPrn(e.target.value)} aria-label="PRN" />
        <button className="btn btn-primary">Show attendance</button>
        {data && <ExportButtons query={{ scope: 'student', prn: data.summary.prn }} />}
      </form>
      {loading && <Spinner />}
      <ErrorNote error={error} />
      {data && <StudentReport data={data} threshold={threshold} />}
    </>
  )
}

function CourseTab({ threshold }) {
  const [courses, setCourses] = useState([])
  const [courseId, setCourseId] = useState('')
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.get('/courses').then((c) => {
      setCourses(c)
      if (c.length) setCourseId(String(c[0].course_id))
    }).catch(setError)
  }, [])
  useEffect(() => {
    if (courseId) api.get(`/attendance/course/${courseId}`).then(setData).catch(setError)
  }, [courseId])

  return (
    <>
      <div className="mb-5 flex flex-wrap gap-2">
        <select className="input w-auto" value={courseId} onChange={(e) => setCourseId(e.target.value)} aria-label="Course">
          {courses.map((c) => (
            <option key={c.course_id} value={c.course_id}>
              {c.code} {c.name}
            </option>
          ))}
        </select>
        {courseId && <ExportButtons query={{ scope: 'course', course_id: courseId }} />}
      </div>
      <ErrorNote error={error} />
      {data && (
        <div className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
          <div className="sheet overflow-x-auto">
            <table className="register min-w-[620px]">
              <thead>
                <tr>
                  <th className="roll">Roll</th>
                  <th>Student</th>
                  <th className="text-right">Present</th>
                  <th className="text-right">Late</th>
                  <th className="text-right">Absent</th>
                  <th className="text-right">Attendance</th>
                </tr>
              </thead>
              <tbody>
                {data.students.map((s) => (
                  <tr key={s.prn} className={s.is_shortage ? 'bg-absent/5' : ''}>
                    <td className="roll">{s.roll_no}</td>
                    <td>
                      {s.full_name} <span className="text-xs text-muted">{s.prn}</span>
                    </td>
                    <td className="tnum text-right">{s.present_count}</td>
                    <td className="tnum text-right">{s.late_count}</td>
                    <td className="tnum text-right">{s.absent_count}</td>
                    <td className="text-right">
                      <Pct value={s.attendance_pct} threshold={threshold} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="sheet overflow-x-auto">
            <table className="register">
              <thead>
                <tr>
                  <th>Lecture</th>
                  <th>Status</th>
                  <th className="text-right">P / L / A</th>
                </tr>
              </thead>
              <tbody>
                {data.sessions.map((x) => (
                  <tr key={x.session_id}>
                    <td className="whitespace-nowrap">
                      {fmtDate(x.session_date)} <span className="tnum text-muted">{x.start_time?.slice(0, 5)}</span>
                    </td>
                    <td>
                      <SessionStatus status={x.status} />
                    </td>
                    <td className="tnum text-right">
                      <span className="text-ink">{x.present_count}</span> / <span className="text-late">{x.late_count}</span> /{' '}
                      <span className="text-absent">{x.absent_count}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}

function DateTab() {
  const [day, setDay] = useState(todayISO())
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    setError(null)
    api.get(`/attendance/date/${day}`).then(setData).catch(setError)
  }, [day])
  return (
    <>
      <div className="mb-5 flex flex-wrap gap-2">
        <input type="date" className="input w-auto" value={day} onChange={(e) => setDay(e.target.value)} aria-label="Date" />
        <ExportButtons query={{ scope: 'date', date: day }} />
      </div>
      <ErrorNote error={error} />
      {data && !data.sessions.length && <Empty title="No lectures on this date" />}
      {data?.sessions.map((x) => (
        <section key={x.session_id} className="mb-6">
          <h3 className="mb-2 text-base">
            {x.course_code} at {x.start_time?.slice(0, 5)} <span className="text-sm font-normal text-muted">({x.teacher_name || 'no teacher'})</span>
          </h3>
          <div className="sheet overflow-x-auto">
            <table className="register">
              <tbody>
                {data.records
                  .filter((r) => r.session_id === x.session_id)
                  .map((r) => (
                    <tr key={r.prn}>
                      <td className="roll">{r.roll_no}</td>
                      <td>{r.full_name}</td>
                      <td className="text-xs text-muted">{fmtDateTime(r.marked_at)}</td>
                      <td className="text-center">
                        <Mark status={r.status} />
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </>
  )
}

function ShortageTab({ threshold }) {
  const { isAdmin } = useAuth()
  const toast = useToast()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [sending, setSending] = useState(false)
  useEffect(() => {
    api.get('/attendance/shortage').then(setData).catch(setError)
  }, [])
  const sendAlerts = async () => {
    setSending(true)
    try {
      const res = await api.post('/admin/jobs/shortage_alerts')
      const r = res.result
      toast.success(`Alerts: ${r.sent} e-mailed, ${r.dry_run} logged only, ${r.skipped} already warned this week`)
    } catch (err) {
      toast.error(err)
    } finally {
      setSending(false)
    }
  }
  return (
    <>
      <div className="mb-5 flex flex-wrap gap-2">
        <ExportButtons query={{ scope: 'shortage' }} />
        {isAdmin && (
          <button className="btn btn-primary btn-sm" disabled={sending} onClick={sendAlerts}>
            E-mail shortage alerts now
          </button>
        )}
      </div>
      <ErrorNote error={error} />
      {data && (
        <div className="sheet overflow-x-auto">
          {!data.items.length ? (
            <Empty title={`Everyone is at or above ${threshold}%`} />
          ) : (
            <table className="register min-w-[640px]">
              <thead>
                <tr>
                  <th>Student</th>
                  <th>Course</th>
                  <th className="text-right">Attended</th>
                  <th className="text-right">Attendance</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={`${r.prn}-${r.course_id}`}>
                    <td>
                      {r.full_name} <span className="text-xs text-muted">{r.prn}</span>
                    </td>
                    <td>{r.course_code}</td>
                    <td className="tnum text-right">
                      {r.present_count + r.late_count}/{r.sessions_held}
                    </td>
                    <td className="text-right">
                      <Pct value={r.attendance_pct} threshold={threshold} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </>
  )
}

export default function Reports() {
  const [params] = useSearchParams()
  const [tab, setTab] = useState(params.get('prn') ? 'student' : 'course')
  const [threshold, setThreshold] = useState(75)
  useEffect(() => {
    api.get('/config/public').then((c) => setThreshold(c.shortage_threshold)).catch(() => {})
  }, [])
  return (
    <>
      <PageHeader title="Registers and exports" description="Every view can be exported as CSV, Excel or PDF." />
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'course', label: 'By course' },
          { value: 'student', label: 'By student' },
          { value: 'date', label: 'By date' },
          { value: 'shortage', label: `Below ${threshold}%` },
        ]}
      />
      {tab === 'student' && <StudentTab initialPrn={params.get('prn')} threshold={threshold} />}
      {tab === 'course' && <CourseTab threshold={threshold} />}
      {tab === 'date' && <DateTab />}
      {tab === 'shortage' && <ShortageTab threshold={threshold} />}
    </>
  )
}
