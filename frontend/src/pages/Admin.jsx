import { useState } from 'react'
import { api } from '../api/client'
import { Chip, Empty, ErrorNote, Field, PageHeader, Spinner, Tabs, fmtDateTime } from '../components/ui'
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
  const [form, setForm] = useState({ employee_code: '', full_name: '', email: '', branch: 'CS', designation: 'Assistant Professor' })
  const [error, setError] = useState(null)
  const [created, setCreated] = useState(null)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      const res = await api.post('/teachers', form)
      setCreated(res)
      toast.success('Teacher added')
      list.reload()
    } catch (err) {
      setError(err)
    }
  }
  return (
    <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
      <div className="sheet overflow-x-auto">
        <table className="register">
          <thead>
            <tr>
              <th>Teacher</th>
              <th>Branch</th>
              <th>Sign-in</th>
            </tr>
          </thead>
          <tbody>
            {list.data?.map((t) => (
              <tr key={t.teacher_id}>
                <td>
                  {t.full_name} <div className="text-xs text-muted">{t.designation}, {t.employee_code}</div>
                </td>
                <td>{t.branch}</td>
                <td className="text-xs">{t.email}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form onSubmit={submit} className="sheet space-y-3 p-4">
        <h2 className="text-lg">Add a teacher</h2>
        <Field label="Employee code">{(id) => <input id={id} className="input" required value={form.employee_code} onChange={set('employee_code')} />}</Field>
        <Field label="Full name">{(id) => <input id={id} className="input" required value={form.full_name} onChange={set('full_name')} />}</Field>
        <Field label="E-mail">{(id) => <input id={id} type="email" className="input" required value={form.email} onChange={set('email')} />}</Field>
        <Field label="Branch code">{(id) => <input id={id} className="input uppercase" required value={form.branch} onChange={set('branch')} />}</Field>
        <ErrorNote error={error} />
        <button className="btn btn-primary">Add teacher</button>
        {created?.temp_password && (
          <p className="text-sm">
            One-time password for {created.username}: <span className="tnum font-bold">{created.temp_password}</span>
          </p>
        )}
      </form>
    </div>
  )
}

export default function Admin() {
  const [tab, setTab] = useState('system')
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
        ]}
      />
      {tab === 'system' && <System />}
      {tab === 'audit' && <Audit />}
      {tab === 'sagas' && <Sagas />}
      {tab === 'teachers' && <Teachers />}
    </>
  )
}
