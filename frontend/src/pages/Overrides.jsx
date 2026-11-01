import { useMemo, useState } from 'react'
import { api } from '../api/client'
import { Chip, Empty, ErrorNote, Field, Mark, Modal, PageHeader, Spinner, Tabs, fmtDate, fmtDateTime } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { useApi } from '../hooks/useApi'

const STATUS_TONE = { PENDING: 'late', APPROVED: 'ink', REJECTED: 'absent' }

function NewCorrection({ open, onClose, onDone }) {
  const { user, isStaff } = useAuth()
  const toast = useToast()
  const [form, setForm] = useState({ session_id: '', prn: '', requested_status: 'PRESENT', late_minutes: '', reason: '' })
  const [error, setError] = useState(null)
  // students pick from their own history; staff type a session id + PRN (or come from the register)
  const history = useApi(
    () => (open && !isStaff && user?.prn ? api.get(`/attendance/student/${user.prn}`) : Promise.resolve(null)),
    [open],
  )
  const choices = useMemo(() => (history.data?.history || []).filter((h) => h.status !== 'PRESENT'), [history.data])
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    try {
      await api.post('/overrides', {
        session_id: Number(form.session_id),
        prn: isStaff ? form.prn.trim().toUpperCase() : user.prn,
        requested_status: form.requested_status,
        late_minutes: form.requested_status === 'LATE' && form.late_minutes ? Number(form.late_minutes) : null,
        reason: form.reason.trim(),
        apply_now: true,
      })
      toast.success(isStaff ? 'Correction applied and logged' : 'Request sent to your teacher')
      onDone()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <Modal
      open={open}
      title={isStaff ? 'Correct an attendance mark' : 'Request a correction'}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-quiet" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" form="override-form">
            {isStaff ? 'Apply correction' : 'Send request'}
          </button>
        </>
      }
    >
      <form id="override-form" onSubmit={submit} className="grid gap-4">
        {isStaff ? (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Session id">{(id) => <input id={id} type="number" className="input" required value={form.session_id} onChange={set('session_id')} />}</Field>
            <Field label="Student PRN">{(id) => <input id={id} className="input uppercase" required value={form.prn} onChange={set('prn')} />}</Field>
          </div>
        ) : (
          <Field label="Lecture" hint="Only lectures where you are not marked present are listed">
            {(id) => (
              <select id={id} className="input" required value={form.session_id} onChange={set('session_id')}>
                <option value="">Choose a lecture</option>
                {choices.map((h) => (
                  <option key={h.session_id} value={h.session_id}>
                    {fmtDate(h.session_date)} {h.start_time} {h.course_code} ({(h.status || 'not marked').toLowerCase()})
                  </option>
                ))}
              </select>
            )}
          </Field>
        )}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Should be">
            {(id) => (
              <select id={id} className="input" value={form.requested_status} onChange={set('requested_status')}>
                <option value="PRESENT">Present</option>
                <option value="LATE">Late</option>
                {isStaff && <option value="ABSENT">Absent</option>}
              </select>
            )}
          </Field>
          {form.requested_status === 'LATE' && (
            <Field label="Minutes late">{(id) => <input id={id} type="number" min="0" max="600" className="input" value={form.late_minutes} onChange={set('late_minutes')} />}</Field>
          )}
        </div>
        <Field label="Reason" hint="Stored permanently in the audit log">
          {(id) => <textarea id={id} className="input min-h-[90px]" required minLength={5} maxLength={500} value={form.reason} onChange={set('reason')} />}
        </Field>
        <ErrorNote error={error} />
      </form>
    </Modal>
  )
}

export default function Overrides() {
  const { isStaff } = useAuth()
  const toast = useToast()
  const [status, setStatus] = useState(isStaff ? 'PENDING' : '')
  const list = useApi(() => api.get('/overrides', { status }), [status])
  const [creating, setCreating] = useState(false)

  const decide = async (item, approve) => {
    const note = window.prompt(approve ? 'Note for the student (optional)' : 'Why is this rejected?') ?? null
    if (note === null && !approve) return
    try {
      await api.post(`/overrides/${item.override_id}/${approve ? 'approve' : 'reject'}`, { note: note || null })
      toast.success(approve ? 'Correction approved' : 'Correction rejected')
      list.reload()
    } catch (err) {
      toast.error(err)
    }
  }

  return (
    <>
      <PageHeader
        title={isStaff ? 'Corrections' : 'Correction requests'}
        description={
          isStaff
            ? 'Every manual change records who made it and why. Approved requests rewrite the mark through a stored procedure and are audited by database triggers.'
            : 'Think a mark is wrong? Ask your teacher to correct it.'
        }
        actions={
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            {isStaff ? 'Correct a mark' : 'Request a correction'}
          </button>
        }
      />
      <Tabs
        value={status}
        onChange={setStatus}
        tabs={[
          { value: 'PENDING', label: 'Waiting' },
          { value: 'APPROVED', label: 'Approved' },
          { value: 'REJECTED', label: 'Rejected' },
          { value: '', label: 'All' },
        ]}
      />
      <ErrorNote error={list.error} />
      <div className="sheet overflow-x-auto">
        {list.loading ? (
          <Spinner className="p-4" />
        ) : !list.data?.length ? (
          <Empty title="No requests here" />
        ) : (
          <table className="register min-w-[820px]">
            <thead>
              <tr>
                <th>Lecture</th>
                <th>Student</th>
                <th className="text-center">Change</th>
                <th>Reason</th>
                <th>Status</th>
                {isStaff && <th />}
              </tr>
            </thead>
            <tbody>
              {list.data.map((o) => (
                <tr key={o.override_id}>
                  <td className="whitespace-nowrap">
                    <span className="font-bold">{o.course_code}</span>
                    <div className="text-xs text-muted">
                      {fmtDate(o.session_date)} {o.start_time}, session {o.session_id}
                    </div>
                  </td>
                  <td>
                    {o.full_name}
                    <div className="text-xs text-muted">{o.prn}</div>
                  </td>
                  <td className="whitespace-nowrap text-center">
                    <Mark status={o.current_status} /> <span className="px-1 text-muted">to</span> <Mark status={o.requested_status} />
                  </td>
                  <td className="max-w-xs text-sm">
                    {o.reason}
                    <div className="text-xs text-muted">
                      {o.requested_by_username || 'unknown'}, {fmtDateTime(o.created_at)}
                    </div>
                    {o.review_note && <div className="mt-1 text-xs">Note: {o.review_note}</div>}
                  </td>
                  <td>
                    <Chip tone={STATUS_TONE[o.status]}>{o.status.toLowerCase()}</Chip>
                  </td>
                  {isStaff && (
                    <td>
                      {o.status === 'PENDING' && (
                        <div className="flex justify-end gap-1.5">
                          <button className="btn btn-quiet btn-sm" onClick={() => decide(o, false)}>
                            Reject
                          </button>
                          <button className="btn btn-primary btn-sm" onClick={() => decide(o, true)}>
                            Approve
                          </button>
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <NewCorrection
        open={creating}
        onClose={() => setCreating(false)}
        onDone={() => {
          setCreating(false)
          list.reload()
        }}
      />
    </>
  )
}
