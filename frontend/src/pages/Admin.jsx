import { useEffect, useState } from 'react'
import { api } from '../api/client'
import {
  Chip,
  Empty,
  ErrorNote,
  Field,
  Modal,
  PageHeader,
  SessionStatus,
  Spinner,
  Tabs,
  fmtDate,
  fmtDateTime,
  hourSlot,
  todayISO,
} from '../components/ui'
import { useToast } from '../context/ToastContext'
import { useApi } from '../hooks/useApi'

const JOBS = [
  { id: 'auto_close_sessions', label: 'Close finished sessions', note: 'Runs every 5 minutes. Calls the auto_close_expired_sessions procedure (a cursor over open sessions).' },
  { id: 'recover_sagas', label: 'Recover interrupted sagas', note: 'Runs every 10 minutes. Finishes or compensates registrations and deletions left half-way.' },
  { id: 'daily_summary', label: 'Send teachers their daily summary', note: 'Runs every evening.' },
  { id: 'shortage_alerts', label: 'E-mail shortage alerts', note: 'Runs weekly; skips students already warned in the last 6 days.' },
]

function System() {
  const health = useApi(() => api.get('/health'), [])
  const toast = useToast()
  const [results, setResults] = useState({})
  const run = async (job) => {
    try {
      const res = await api.post(`/admin/jobs/${job}`)
      setResults((r) => ({ ...r, [job]: res.result }))
      toast.success('Job finished')
    } catch (err) {
      toast.error(err)
    }
  }
  const reload = async () => {
    try {
      const res = await api.post('/admin/index/reload')
      toast.success(`Vector index reloaded: ${res.embeddings} templates`)
      health.reload()
    } catch (err) {
      toast.error(err)
    }
  }
  const h = health.data
  return (
    <div className="grid gap-8 lg:grid-cols-2">
      <section>
        <h2 className="mb-2 text-lg">Services</h2>
        {health.loading ? (
          <Spinner />
        ) : h ? (
          <dl className="sheet divide-y divide-line text-sm">
            {[
              ['MySQL', h.mysql ? 'Reachable' : 'Unreachable', h.mysql],
              ['MongoDB', h.mongo ? 'Reachable' : 'Unreachable', h.mongo],
              ['Face engine', `${h.engine.name || '–'} (${h.engine.status})`, h.engine.status === 'ready'],
              ['Vector index', `${h.engine.index.embeddings} templates, ${h.engine.index.students} students, ${h.engine.index.backend}, version ${h.engine.index.version}`, true],
              ['Live connections', String(h.websocket_clients), true],
            ].map(([k, v, ok]) => (
              <div key={k} className="flex items-center justify-between gap-4 px-4 py-2.5">
                <dt className="text-muted">{k}</dt>
                <dd className={ok ? '' : 'font-bold text-absent'}>{v}</dd>
              </div>
            ))}
            {h.engine.error && <p className="px-4 py-2.5 text-absent">{h.engine.error}</p>}
          </dl>
        ) : (
          <ErrorNote error={health.error} />
        )}
        <button className="btn btn-quiet btn-sm mt-3" onClick={reload}>
          Reload vector index
        </button>
      </section>
      <section>
        <h2 className="mb-2 text-lg">Background jobs</h2>
        <ul className="sheet divide-y divide-line">
          {JOBS.map((j) => (
            <li key={j.id} className="px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <p className="font-bold">{j.label}</p>
                <button className="btn btn-quiet btn-sm" onClick={() => run(j.id)}>
                  Run now
                </button>
              </div>
              <p className="text-sm text-muted">{j.note}</p>
              {results[j.id] !== undefined && <pre className="mt-2 overflow-x-auto rounded bg-panel2 p-2 text-xs">{JSON.stringify(results[j.id], null, 2)}</pre>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

const SAGA_TONE = { COMPLETED: 'ink', COMPENSATED: 'late', FAILED: 'absent', STARTED: 'muted', COMPENSATING: 'late' }

function Sagas() {
  const sagas = useApi(() => api.get('/admin/sagas', { limit: 100 }), [])
  return (
    <>
      <p className="mb-3 max-w-prose text-sm text-muted">
        Registration and deletion touch both databases. Each step is a local transaction; if a later step fails the
        earlier ones are undone in reverse order (compensation).
      </p>
      <div className="sheet overflow-x-auto">
        {sagas.loading ? (
          <Spinner className="p-4" />
        ) : !sagas.data?.length ? (
          <Empty title="No sagas yet" />
        ) : (
          <table className="register min-w-[760px]">
            <thead>
              <tr>
                <th>When</th>
                <th>Type</th>
                <th>Subject</th>
                <th>Steps</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {sagas.data.map((s) => (
                <tr key={s.saga_id}>
                  <td className="whitespace-nowrap text-xs">{fmtDateTime(s.created_at)}</td>
                  <td>{s.saga_type.toLowerCase().replace('_', ' ')}</td>
                  <td className="max-w-[140px] truncate text-xs" title={s.subject}>
                    {s.subject}
                  </td>
                  <td className="text-xs">
                    {s.steps.map((st) => (
                      <span key={st.name} className="mr-2 inline-block">
                        {st.name.replaceAll('_', ' ')}: <span className={st.status === 'DONE' ? 'text-ink' : st.status.includes('FAIL') ? 'text-absent' : 'text-late'}>{st.status.toLowerCase()}</span>
                      </span>
                    ))}
                    {s.error_message && <div className="mt-1 text-absent">{s.error_message}</div>}
                  </td>
                  <td>
                    <Chip tone={SAGA_TONE[s.status]}>{s.status.toLowerCase()}</Chip>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}

function Diff({ oldV, newV }) {
  const keys = [...new Set([...Object.keys(oldV || {}), ...Object.keys(newV || {})])]
  return (
    <div className="text-xs">
      {keys.map((k) => {
        const a = oldV?.[k]
        const b = newV?.[k]
        if (JSON.stringify(a) === JSON.stringify(b)) return null
        return (
          <div key={k}>
            <span className="text-muted">{k}:</span> {a !== undefined && <span className="text-absent line-through">{String(a)}</span>} {b !== undefined && <span className="text-ink">{String(b)}</span>}
          </div>
        )
      })}
    </div>
  )
}

function Audit() {
  const [filters, setFilters] = useState({ table: '', action: '', record_id: '' })
  const audit = useApi(() => api.get('/admin/audit', { ...filters, limit: 200 }), [JSON.stringify(filters)])
  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value }))
  return (
    <>
      <p className="mb-3 max-w-prose text-sm text-muted">
        Written by MySQL triggers, not by the application. The application database user can read this table but
        cannot change or delete rows.
      </p>
      <div className="mb-3 flex flex-wrap gap-2">
        <select className="input w-auto" value={filters.table} onChange={set('table')} aria-label="Table">
          <option value="">All tables</option>
          <option value="attendance">attendance</option>
          <option value="students">students</option>
          <option value="override_requests">override_requests</option>
        </select>
        <select className="input w-auto" value={filters.action} onChange={set('action')} aria-label="Action">
          <option value="">All actions</option>
          {['INSERT', 'UPDATE', 'DELETE', 'OVERRIDE', 'ERASE'].map((a) => (
            <option key={a} value={a}>
              {a.toLowerCase()}
            </option>
          ))}
        </select>
        <input className="input w-auto" placeholder="Record id" value={filters.record_id} onChange={set('record_id')} aria-label="Record id" />
      </div>
      <div className="sheet overflow-x-auto">
        {audit.loading ? (
          <Spinner className="p-4" />
        ) : !audit.data?.length ? (
          <Empty title="No audit entries match" />
        ) : (
          <table className="register min-w-[860px]">
            <thead>
              <tr>
                <th>When</th>
                <th>What</th>
                <th>Change</th>
                <th>Why</th>
                <th>Who</th>
              </tr>
            </thead>
            <tbody>
              {audit.data.map((a) => (
                <tr key={a.audit_id}>
                  <td className="whitespace-nowrap text-xs">{fmtDateTime(a.changed_at)}</td>
                  <td className="text-xs">
                    <Chip tone={a.action === 'ERASE' || a.action === 'DELETE' ? 'absent' : a.action === 'OVERRIDE' ? 'late' : 'muted'}>{a.action.toLowerCase()}</Chip>
                    <div className="mt-1">
                      {a.table_name} <span className="text-muted">{a.record_id.length > 20 ? `${a.record_id.slice(0, 12)}…` : a.record_id}</span>
                    </div>
                  </td>
                  <td>
                    <Diff oldV={a.old_values} newV={a.new_values} />
                  </td>
                  <td className="max-w-xs text-xs">{a.reason || <span className="text-muted">–</span>}</td>
                  <td className="text-xs">
                    {a.changed_by_username || '–'}
                    <div className="text-muted">{a.db_user}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}

function Teachers() {
  const toast = useToast()
  const list = useApi(() => api.get('/teachers'), [])
  const [form, setForm] = useState({ employee_code: '', full_name: '', email: '', branch: 'CS', designation: 'Assistant Professor', password: '' })
  const [error, setError] = useState(null)
  const [created, setCreated] = useState(null)
  const [resetting, setResetting] = useState(null)
  const [newPassword, setNewPassword] = useState('')
  const [resetError, setResetError] = useState(null)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      const res = await api.post('/teachers', { ...form, password: form.password || null })
      setCreated(res)
      toast.success(`${form.full_name} can sign in with ${res.username}`)
      setForm({ employee_code: '', full_name: '', email: '', branch: 'CS', designation: 'Assistant Professor', password: '' })
      list.reload()
    } catch (err) {
      setError(err)
    }
  }

  const resetPassword = async (e) => {
    e.preventDefault()
    setResetError(null)
    try {
      const res = await api.post(`/teachers/${resetting.teacher_id}/password`, { password: newPassword || null })
      toast.success(res.temp_password ? `One-time password: ${res.temp_password}` : `Password set for ${res.username}`)
      setResetting(null)
      setNewPassword('')
    } catch (err) {
      setResetError(err)
    }
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
      <div>
        <p className="mb-3 max-w-prose text-sm text-muted">
          Teachers never register themselves. An admin adds them here and picks the password; the teacher signs in with
          the <span className="font-semibold">employee code</span>, not an e-mail, and can change the password from
          their own account afterwards.
        </p>
        <div className="sheet overflow-x-auto">
          <table className="register min-w-[560px]">
            <thead>
              <tr>
                <th>Teacher</th>
                <th>Branch</th>
                <th>Signs in with</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data?.map((t) => (
                <tr key={t.teacher_id}>
                  <td>
                    {t.full_name}
                    <div className="text-xs text-muted">
                      {t.designation}
                      {t.email ? `, ${t.email}` : ''}
                    </div>
                  </td>
                  <td>{t.branch}</td>
                  <td className="font-bold">{t.employee_code}</td>
                  <td>
                    <div className="flex justify-end">
                      <button
                        className="btn btn-quiet btn-sm"
                        onClick={() => {
                          setResetting(t)
                          setNewPassword('')
                          setResetError(null)
                        }}
                      >
                        Set password
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <form onSubmit={submit} className="sheet space-y-3 p-4">
        <h2 className="text-lg">Add a teacher</h2>
        <Field label="Employee code" hint="This is the username, e.g. VIT@006">
          {(id) => <input id={id} className="input" required value={form.employee_code} onChange={set('employee_code')} />}
        </Field>
        <Field label="Full name">{(id) => <input id={id} className="input" required value={form.full_name} onChange={set('full_name')} />}</Field>
        <Field label="E-mail" hint="For notifications; not used to sign in">
          {(id) => <input id={id} type="email" className="input" required value={form.email} onChange={set('email')} />}
        </Field>
        <Field label="Branch code">{(id) => <input id={id} className="input uppercase" required value={form.branch} onChange={set('branch')} />}</Field>
        <Field label="Password" hint="Leave empty for a one-time password the teacher must change">
          {(id) => <input id={id} type="text" className="input" autoComplete="new-password" minLength={8} value={form.password} onChange={set('password')} />}
        </Field>
        <ErrorNote error={error} />
        <button className="btn btn-primary">Add teacher</button>
        {created && (
          <p className="text-sm">
            {created.username} can sign in now
            {created.temp_password && (
              <>
                {' '}with the one-time password <span className="tnum font-bold">{created.temp_password}</span>
              </>
            )}
            .
          </p>
        )}
      </form>

      <Modal
        open={!!resetting}
        title={`Password for ${resetting?.full_name || ''}`}
        onClose={() => setResetting(null)}
        footer={
          <>
            <button className="btn btn-quiet" onClick={() => setResetting(null)}>
              Cancel
            </button>
            <button className="btn btn-primary" form="teacher-password-form">
              Save password
            </button>
          </>
        }
      >
        <form id="teacher-password-form" onSubmit={resetPassword} className="space-y-3">
          <p className="text-sm text-muted">
            {resetting?.full_name} signs in with <span className="font-bold">{resetting?.employee_code}</span>. Leave
            the field empty to generate a one-time password they must change at first sign-in.
          </p>
          <Field label="New password" hint="At least 8 characters with a letter and a digit">
            {(id) => (
              <input id={id} type="text" className="input" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            )}
          </Field>
          <ErrorNote error={resetError} />
        </form>
      </Modal>
    </div>
  )
}

function PendingApprovals() {
  const toast = useToast()
  const pending = useApi(() => api.get('/students/pending'), [])
  const [busy, setBusy] = useState(null)
  const [rejecting, setRejecting] = useState(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState(null)

  const approve = async (prn) => {
    setBusy(prn)
    try {
      await api.post(`/students/${prn}/approve`)
      toast.success(`${prn} approved and can sign in now`)
      window.dispatchEvent(new Event('sfa:approvals-changed'))
      pending.reload()
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(null)
    }
  }

  const reject = async (e) => {
    e.preventDefault()
    setError(null)
    setBusy(rejecting.prn)
    try {
      await api.post(`/students/${rejecting.prn}/reject`, { reason: reason.trim() })
      toast.success(`${rejecting.prn} rejected; account and face templates erased`)
      window.dispatchEvent(new Event('sfa:approvals-changed'))
      setRejecting(null)
      setReason('')
      pending.reload()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <p className="mb-3 max-w-prose text-sm text-muted">
        Students who created their own account (<span className="font-semibold">Sign up</span> on the login page, or a
        class code) wait here. They cannot sign in until you approve them. Rejecting erases the account and the
        encrypted face templates.
      </p>
      <ErrorNote error={pending.error} className="mb-3" />
      <div className="sheet overflow-x-auto">
        {pending.loading ? (
          <Spinner className="p-4" />
        ) : !pending.data?.items?.length ? (
          <Empty title="Nobody is waiting for approval">
            New sign-ups from the login page show up here within seconds.
          </Empty>
        ) : (
          <table className="register min-w-[880px]">
            <thead>
              <tr>
                <th>PRN</th>
                <th>Name</th>
                <th>Branch</th>
                <th>Year</th>
                <th>Division</th>
                <th className="roll">Roll</th>
                <th>Contact</th>
                <th className="text-right">Faces</th>
                <th>Signed up</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {pending.data.items.map((s) => (
                <tr key={s.prn}>
                  <td className="font-bold">{s.prn}</td>
                  <td className="whitespace-nowrap">{s.full_name}</td>
                  <td>{s.branch}</td>
                  <td>Year {s.year}</td>
                  <td>{s.division}</td>
                  <td className="roll">{s.roll_no}</td>
                  <td className="text-xs text-muted">
                    {s.email}
                    {s.phone && <div>{s.phone}</div>}
                  </td>
                  <td className="tnum text-right">{s.face_templates ?? '-'}</td>
                  <td className="whitespace-nowrap text-xs">{fmtDateTime(s.created_at)}</td>
                  <td>
                    <div className="flex justify-end gap-1.5">
                      <button className="btn btn-primary btn-sm" disabled={busy === s.prn} onClick={() => approve(s.prn)}>
                        Approve
                      </button>
                      <button
                        className="btn btn-danger btn-sm"
                        disabled={busy === s.prn}
                        onClick={() => {
                          setRejecting(s)
                          setReason('')
                          setError(null)
                        }}
                      >
                        Reject
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Modal
        open={!!rejecting}
        title={`Reject ${rejecting?.prn || ''}`}
        onClose={() => setRejecting(null)}
        footer={
          <>
            <button className="btn btn-quiet" onClick={() => setRejecting(null)}>
              Cancel
            </button>
            <button className="btn btn-danger" form="reject-form" disabled={reason.trim().length < 5}>
              Reject and erase
            </button>
          </>
        }
      >
        <form id="reject-form" onSubmit={reject} className="space-y-3">
          <p className="text-sm text-muted">
            {rejecting?.full_name} ({rejecting?.prn}) is deleted together with their login and their face templates.
            This cannot be undone; they can sign up again afterwards.
          </p>
          <Field label="Reason" hint="Kept in the audit trail, at least 5 characters">
            {(id) => (
              <input
                id={id}
                className="input"
                required
                minLength={5}
                maxLength={500}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            )}
          </Field>
          <ErrorNote error={error} />
        </form>
      </Modal>
    </>
  )
}

/** Live six-digit code + QR of one open session. Both change every QR window. */
function AttendanceCodeCard({ session }) {
  const [qr, setQr] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    let timer
    let alive = true
    const load = async () => {
      try {
        const data = await api.get(`/sessions/${session.session_id}/qr`)
        if (!alive) return
        setQr(data)
        setError(null)
        timer = setTimeout(load, Math.max(2, data.expires_in) * 1000)
      } catch (err) {
        if (alive) setError(err)
      }
    }
    load()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [session.session_id])

  return (
    <div className="sheet p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-bold">
          {session.course_code} <span className="font-normal text-muted">{session.topic || session.room || ''}</span>
        </p>
        <SessionStatus status={session.status} />
      </div>
      <p className="mt-0.5 text-xs text-muted">
        {fmtDate(session.session_date)}, {session.start_time}-{session.end_time}
      </p>
      <ErrorNote error={error} className="mt-3" />
      {qr && (
        <div className="mt-4 flex flex-col items-center gap-3 sm:flex-row sm:gap-6">
          <img src={qr.qr_png} alt="Rotating attendance QR code" className="w-40 rounded bg-white p-2" />
          <div className="text-center sm:text-left">
            <p className="eyebrow">Six-digit code</p>
            <p className="tnum text-5xl font-bold tracking-[0.2em]">{qr.code}</p>
            <p className="mt-1 text-xs text-muted">Changes in {qr.expires_in}s. Session {session.session_id}.</p>
          </div>
        </div>
      )}
      {!qr && !error && <Spinner className="mt-4" />}
    </div>
  )
}

function AttendanceCode() {
  const toast = useToast()
  const [date, setDate] = useState(todayISO())
  const sessions = useApi(() => api.get('/sessions', date ? { date } : undefined), [date])
  const courses = useApi(() => api.get('/courses'), [])
  const [startCourse, setStartCourse] = useState('')
  const [showFor, setShowFor] = useState(null)

  // one click: a lecture for the clock hour we are in, already open, code on screen
  const startNow = async () => {
    const course_id = Number(startCourse || courses.data?.[0]?.course_id)
    if (!course_id) return
    try {
      const s = await api.post('/sessions/now', { course_id })
      toast.success(`${s.course_code} is open, ${s.start_time}-${s.end_time}`)
      setDate(todayISO())
      sessions.reload()
      setShowFor(s)
    } catch (err) {
      toast.error(err)
    }
  }

  const openSession = async (s, force) => {
    await api.post(`/sessions/${s.session_id}/open`, { force })
    toast.success(`${s.course_code} is open`)
    const fresh = await sessions.reload()
    const row = (fresh || []).find((x) => x.session_id === s.session_id)
    setShowFor(row || { ...s, status: 'OPEN' })
  }

  const open = async (s) => {
    try {
      await openSession(s, false)
    } catch (err) {
      if (err.code === 'OUTSIDE_SESSION_WINDOW' && window.confirm(`${err.message}. Open it anyway?`)) {
        try {
          await openSession(s, true)
        } catch (err2) {
          toast.error(err2)
        }
      } else {
        toast.error(err)
      }
    }
  }

  const rows = sessions.data || []
  const openRows = rows.filter((s) => s.status === 'OPEN')

  return (
    <>
      <p className="mb-4 max-w-prose text-sm text-muted">
        When the camera does not recognise a student, they mark themselves with this code on their{' '}
        <span className="font-semibold">Mark with attendance code</span> page; the QR below takes them straight there. A
        code belongs to one lecture and only exists while that lecture is{' '}
        <span className="font-semibold">open</span>, so open it first. The six digits change every 30 seconds.
      </p>
      <div className="sheet mb-4 flex flex-wrap items-end gap-3 p-4">
        <Field label="Start a lecture now" hint={`Recorded as the ${hourSlot().start}-${hourSlot().end} lecture`}>
          {(id) => (
            <select id={id} className="input w-auto" value={startCourse} onChange={(e) => setStartCourse(e.target.value)}>
              {(courses.data || []).map((c) => (
                <option key={c.course_id} value={c.course_id}>
                  {c.code} {c.name}
                </option>
              ))}
            </select>
          )}
        </Field>
        <button className="btn btn-primary" onClick={startNow} disabled={!courses.data?.length}>
          Start and show the code
        </button>
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input type="date" className="input w-auto" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Date" />
        <button className="btn btn-quiet btn-sm" onClick={() => setDate(todayISO())}>
          Today
        </button>
        <button className="btn btn-quiet btn-sm" onClick={() => setDate('')}>
          All dates
        </button>
        <button className="btn btn-quiet btn-sm" onClick={() => sessions.reload()}>
          Refresh
        </button>
      </div>
      <ErrorNote error={sessions.error} className="mb-3" />

      {openRows.length > 0 && (
        <div className="mb-6 grid gap-4 lg:grid-cols-2">
          {openRows.map((s) => (
            <AttendanceCodeCard key={s.session_id} session={s} />
          ))}
        </div>
      )}

      <div className="sheet overflow-x-auto">
        {sessions.loading ? (
          <Spinner className="p-4" />
        ) : !rows.length ? (
          <Empty title="No lectures on this date">
            Create one under Sessions, then open it to get an attendance code.
          </Empty>
        ) : (
          <table className="register min-w-[700px]">
            <thead>
              <tr>
                <th>Date</th>
                <th>Time</th>
                <th>Course</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.session_id}>
                  <td className="whitespace-nowrap">{fmtDate(s.session_date)}</td>
                  <td className="tnum whitespace-nowrap">
                    {s.start_time}-{s.end_time}
                  </td>
                  <td>
                    <span className="font-bold">{s.course_code}</span>{' '}
                    {s.topic && <span className="text-muted">{s.topic}</span>}
                  </td>
                  <td>
                    <SessionStatus status={s.status} />
                  </td>
                  <td>
                    <div className="flex justify-end gap-1.5">
                      {s.status === 'SCHEDULED' && (
                        <button className="btn btn-primary btn-sm" onClick={() => open(s)}>
                          Open and get code
                        </button>
                      )}
                      {s.status === 'OPEN' && (
                        <button className="btn btn-quiet btn-sm" onClick={() => setShowFor(s)}>
                          Show code large
                        </button>
                      )}
                      {s.status !== 'SCHEDULED' && s.status !== 'OPEN' && <Chip>No code: lecture is {s.status.toLowerCase()}</Chip>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Modal open={!!showFor} title={`Attendance code for ${showFor?.course_code || ''}`} onClose={() => setShowFor(null)} wide>
        {showFor && <AttendanceCodeCard session={showFor} />}
      </Modal>
    </>
  )
}

export default function Admin({ initialTab = 'system' }) {
  const [tab, setTab] = useState(initialTab)
  return (
    <>
      <PageHeader title="System and audit" description="Health of the services, background jobs, cross-database sagas and the audit trail." />
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'system', label: 'System' },
          { value: 'audit', label: 'Audit trail' },
          { value: 'sagas', label: 'Sagas' },
          { value: 'teachers', label: 'Teachers' },
          { value: 'pending', label: 'Pending approvals' },
          { value: 'code', label: 'Attendance code' },
        ]}
      />
      {tab === 'system' && <System />}
      {tab === 'audit' && <Audit />}
      {tab === 'sagas' && <Sagas />}
      {tab === 'teachers' && <Teachers />}
      {tab === 'pending' && <PendingApprovals />}
      {tab === 'code' && <AttendanceCode />}
    </>
  )
}
