import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { PhotoCapture } from '../components/PhotoCapture'
import { Empty, ErrorNote, FaceStatus, Modal, PageHeader, Spinner } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { useApi } from '../hooks/useApi'
import { useWebcam } from '../hooks/useWebcam'

const PAGE = 50

function AddPhotosModal({ student, onClose, onDone }) {
  const toast = useToast()
  const { isAdmin } = useAuth()
  const cam = useWebcam({ width: 1280, height: 960 })
  const [photos, setPhotos] = useState([])
  const [replace, setReplace] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const usable = photos.filter((p) => p.result?.accepted)

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const form = new FormData()
      usable.forEach((p, i) => form.append('photos', p.blob, `p${i}.jpg`))
      form.append('replace', replace ? 'true' : 'false')
      const res = await api.form(`/students/${student.prn}/photos`, form)
      toast.success(`${res.embeddings_added} templates added for ${student.full_name}`)
      onDone()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      wide
      title={`Update face of ${student.full_name}`}
      onClose={onClose}
      footer={
        <>
          {isAdmin && (
            <label className="mr-auto flex items-center gap-2 text-sm">
              <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} className="h-4 w-4 accent-[rgb(var(--ink))]" />
              Replace all existing templates
            </label>
          )}
          <button className="btn btn-quiet" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy || usable.length < 5} onClick={save}>
            {busy ? 'Saving…' : `Save ${usable.length} photos`}
          </button>
        </>
      }
    >
      <PhotoCapture cam={cam} photos={photos} setPhotos={setPhotos} prn={student.prn} />
      <ErrorNote error={error} className="mt-3" />
    </Modal>
  )
}

export default function Students() {
  const toast = useToast()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const [filters, setFilters] = useState({ search: '', branch: '', year: '', division: '', face_status: '' })
  const [offset, setOffset] = useState(0)
  const list = useApi(() => api.get('/students', { ...filters, limit: PAGE, offset }), [JSON.stringify(filters), offset])
  const [photosFor, setPhotosFor] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [mode, setMode] = useState('delete')
  const [confirmText, setConfirmText] = useState('')
  const [reason, setReason] = useState('')

  const setFilter = (k) => (e) => {
    setOffset(0)
    setFilters((f) => ({ ...f, [k]: e.target.value }))
  }

  const remove = async () => {
    try {
      if (mode === 'forget') {
        const res = await api.post(`/students/${deleting.prn}/forget`, { confirm_prn: confirmText })
        toast.success(`All data of ${deleting.full_name} erased (${res.certificate})`)
      } else {
        await api.del(`/students/${deleting.prn}`, { reason: reason || undefined })
        toast.success(`${deleting.full_name} deleted`)
      }
      setDeleting(null)
      list.reload()
    } catch (err) {
      toast.error(err)
    }
  }

  const total = list.data?.total ?? 0

  return (
    <>
      <PageHeader
        title="Students"
        description="Profiles live in MySQL; face templates are encrypted in MongoDB and linked by PRN."
        actions={
          <>
            <Link className="btn btn-quiet" to="/students/import">
              Import from CSV
            </Link>
            <Link className="btn btn-primary" to="/students/register">
              Register a student
            </Link>
          </>
        }
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr_1.3fr]">
        <input className="input" placeholder="Search by name, PRN or e-mail" value={filters.search} onChange={setFilter('search')} aria-label="Search" />
        <input className="input" placeholder="Branch (CS)" value={filters.branch} onChange={setFilter('branch')} aria-label="Branch" />
        <select className="input" value={filters.year} onChange={setFilter('year')} aria-label="Year">
          <option value="">Any year</option>
          {[1, 2, 3, 4].map((y) => (
            <option key={y} value={y}>
              Year {y}
            </option>
          ))}
        </select>
        <input className="input" placeholder="Division (A)" value={filters.division} onChange={setFilter('division')} aria-label="Division" />
        <select className="input" value={filters.face_status} onChange={setFilter('face_status')} aria-label="Face status">
          <option value="">Any face status</option>
          <option value="ENROLLED">Face enrolled</option>
          <option value="PENDING">No face yet</option>
          <option value="REENROLL_REQUIRED">Re-enrol face</option>
        </select>
      </div>
      <ErrorNote error={list.error} className="mb-3" />
      <div className="sheet overflow-x-auto">
        {list.loading && !list.data ? (
          <Spinner className="p-4" />
        ) : !list.data?.items.length ? (
          <Empty title="No students found" action={<Link className="btn btn-quiet btn-sm" to="/students/register">Register a student</Link>}>
            Change the filters, or register students one by one or from a CSV file.
          </Empty>
        ) : (
          <table className="register min-w-[820px]">
            <thead>
              <tr>
                <th className="roll">Roll</th>
                <th>Student</th>
                <th>Class</th>
                <th>Face</th>
                <th className="text-right">Templates</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((s) => (
                <tr key={s.prn}>
                  <td className="roll">{s.roll_no}</td>
                  <td>
                    <span className="font-bold">{s.full_name}</span>
                    <div className="text-xs text-muted">
                      {s.prn}, {s.email}
                    </div>
                  </td>
                  <td className="whitespace-nowrap">
                    {s.branch} {s.year}-{s.division}
                  </td>
                  <td>
                    <FaceStatus status={s.face_status} />
                  </td>
                  <td className="tnum text-right">{s.face_templates ?? '–'}</td>
                  <td>
                    <div className="flex justify-end gap-1.5">
                      <button className="btn btn-quiet btn-sm" onClick={() => navigate(`/reports?prn=${s.prn}`)}>
                        Attendance
                      </button>
                      <button className="btn btn-quiet btn-sm" onClick={() => setPhotosFor(s)}>
                        {s.face_status === 'PENDING' ? 'Enrol face' : 'Update face'}
                      </button>
                      {isAdmin && (
                        <button
                          className="btn btn-danger btn-sm"
                          onClick={() => {
                            setDeleting(s)
                            setMode('delete')
                            setConfirmText('')
                            setReason('')
                          }}
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {total > PAGE && (
        <div className="mt-3 flex items-center justify-between text-sm">
          <span className="text-muted">
            {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button className="btn btn-quiet btn-sm" disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>
              Previous
            </button>
            <button className="btn btn-quiet btn-sm" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
              Next
            </button>
          </div>
        </div>
      )}

      {photosFor && (
        <AddPhotosModal
          student={photosFor}
          onClose={() => setPhotosFor(null)}
          onDone={() => {
            setPhotosFor(null)
            list.reload()
          }}
        />
      )}

      <Modal
        open={!!deleting}
        title={`Remove ${deleting?.full_name}`}
        onClose={() => setDeleting(null)}
        footer={
          <>
            <button className="btn btn-quiet" onClick={() => setDeleting(null)}>
              Keep student
            </button>
            <button className="btn btn-danger" disabled={mode === 'forget' && confirmText.toUpperCase() !== deleting?.prn} onClick={remove}>
              {mode === 'forget' ? 'Erase everything' : 'Delete student'}
            </button>
          </>
        }
      >
        <fieldset className="space-y-3 text-sm">
          <label className="flex items-start gap-3">
            <input type="radio" name="mode" checked={mode === 'delete'} onChange={() => setMode('delete')} className="mt-1 accent-[rgb(var(--absent))]" />
            <span>
              <span className="font-bold">Delete student.</span> Removes the profile, enrolments, attendance and face
              templates. Recognition statistics are kept without the name.
            </span>
          </label>
          <label className="flex items-start gap-3">
            <input type="radio" name="mode" checked={mode === 'forget'} onChange={() => setMode('forget')} className="mt-1 accent-[rgb(var(--absent))]" />
            <span>
              <span className="font-bold">Erase everything (right to be forgotten).</span> Also deletes recognition logs,
              photos, notifications and pseudonymises the audit trail. Cannot be undone.
            </span>
          </label>
          {mode === 'delete' ? (
            <input className="input" placeholder="Reason (kept in the audit log)" value={reason} onChange={(e) => setReason(e.target.value)} />
          ) : (
            <input className="input" placeholder={`Type ${deleting?.prn} to confirm`} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
          )}
        </fieldset>
      </Modal>
    </>
  )
}
