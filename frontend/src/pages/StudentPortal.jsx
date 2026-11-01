import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, downloadFile } from '../api/client'
import { ErrorNote, Modal, PageHeader, Spinner } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { useApi } from '../hooks/useApi'
import { StudentReport } from './Reports'

function needed(present, held, threshold) {
  // lectures in a row needed to get back to the threshold
  if (!held) return 0
  const t = threshold / 100
  if (present / held >= t) return 0
  return Math.ceil((t * held - present) / (1 - t))
}

export default function StudentPortal() {
  const { user, logout } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const report = useApi(() => api.get(`/attendance/student/${user.prn}`), [user.prn])
  const config = useApi(() => api.get('/config/public'), [])
  const [erasing, setErasing] = useState(false)
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState(null)
  const threshold = config.data?.shortage_threshold ?? 75

  const erase = async () => {
    setError(null)
    try {
      await api.post(`/students/${user.prn}/forget`, { confirm_prn: confirm })
      toast.success('Your data has been erased')
      logout()
      navigate('/login')
    } catch (err) {
      setError(err)
    }
  }

  const s = report.data?.summary
  const shortCourses = (report.data?.courses || []).filter((c) => c.sessions_held > 0 && c.attendance_pct < threshold)

  return (
    <>
      <PageHeader
        title="My attendance"
        description="Counted over lectures that have finished. Late arrivals count as attended."
        actions={
          <>
            <Link className="btn btn-primary" to="/join">
              Join a class
            </Link>
            <Link className="btn btn-quiet" to="/qr">
              Mark with attendance code
            </Link>
            <button className="btn btn-quiet" onClick={() => downloadFile('/reports/export', { scope: 'student', type: 'pdf' }, 'my_attendance.pdf').catch(toast.error)}>
              Download PDF
            </button>
          </>
        }
      />
      {report.loading && <Spinner />}
      <ErrorNote error={report.error} />
      {s && shortCourses.length > 0 && (
        <div className="mb-6 rounded-2xl border border-absent/50 bg-absent/10 p-4 text-sm">
          <p className="font-bold">You are below {threshold}% in {shortCourses.length} course{shortCourses.length === 1 ? '' : 's'}.</p>
          <ul className="mt-1 list-disc pl-5">
            {shortCourses.map((c) => (
              <li key={c.course_id}>
                {c.course_code}: attend the next {needed(c.present_count + c.late_count, c.sessions_held, threshold)} lectures in a row to reach {threshold}%.
              </li>
            ))}
          </ul>
        </div>
      )}
      {report.data && <StudentReport data={report.data} threshold={threshold} />}

      <section className="mt-10 max-w-prose">
        <h2 className="text-lg">Your face data</h2>
        <p className="mt-1 text-sm text-muted">
          Your photos were turned into encrypted face templates used only to mark attendance. You can erase your
          profile, templates, recognition history and attendance records at any time. This cannot be undone and you will
          no longer be able to sign in.
        </p>
        <button className="btn btn-danger mt-3" onClick={() => setErasing(true)}>
          Erase my data
        </button>
      </section>

      <Modal
        open={erasing}
        title="Erase all my data"
        onClose={() => setErasing(false)}
        footer={
          <>
            <button className="btn btn-quiet" onClick={() => setErasing(false)}>
              Keep my data
            </button>
            <button className="btn btn-danger" disabled={confirm.toUpperCase() !== user.prn} onClick={erase}>
              Erase permanently
            </button>
          </>
        }
      >
        <p className="text-sm">Type your PRN ({user.prn}) to confirm.</p>
        <input className="input mt-3 uppercase" value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-label="PRN confirmation" />
        <ErrorNote error={error} className="mt-3" />
      </Modal>
    </>
  )
}
