import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Copy } from 'lucide-react'
import { api } from '../api/client'
import { PhotoCapture } from '../components/PhotoCapture'
import { ErrorNote, Field, PageHeader } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { useWebcam } from '../hooks/useWebcam'

const EMPTY = { name: '', prn: '', email: '', phone: '', branch: 'CS', year: '2', division: 'A', roll_no: '', password: '' }

export default function RegisterStudent() {
  const toast = useToast()
  const cam = useWebcam({ width: 1280, height: 960 })
  const [form, setForm] = useState(EMPTY)
  const [consent, setConsent] = useState(false)
  const [photos, setPhotos] = useState([])
  const [academic, setAcademic] = useState([])
  const [config, setConfig] = useState({ min_photos: 5, max_photos: 10 })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)

  useEffect(() => {
    api.get('/meta/academic').then((r) => setAcademic(r.branches)).catch(() => {})
    api.get('/config/public').then(setConfig).catch(() => {})
  }, [])

  const branch = academic.find((b) => b.code === form.branch)
  const divisions = useMemo(() => branch?.divisions?.[form.year] || ['A', 'B', 'C'], [branch, form.year])
  const usable = photos.filter((p) => p.result?.accepted)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    if (!consent) return setError('The student must consent to storing their face data.')
    if (usable.length < config.min_photos) return setError(`At least ${config.min_photos} usable photos are needed.`)
    setBusy(true)
    try {
      const data = new FormData()
      Object.entries(form).forEach(([k, v]) => v !== '' && data.append(k, k === 'prn' ? v.toUpperCase() : v))
      data.append('consent', 'true')
      usable.slice(0, config.max_photos).forEach((p, i) => data.append('photos', p.blob, `photo${i}.jpg`))
      const res = await api.form('/students/register', data)
      setDone(res)
      toast.success(`${res.student.full_name} is registered`)
    } catch (err) {
      setError(err)
      // map per-photo problems back onto the thumbnails
      const report = err.details?.photos
      if (report) {
        setPhotos((list) => {
          const accepted = list.filter((p) => p.result?.accepted)
          return list.map((p) => {
            const r = report[accepted.indexOf(p)]
            return r && !r.accepted ? { ...p, result: { ...p.result, accepted: false, messages: r.messages?.length ? r.messages : r.issues } } : p
          })
        })
      }
    } finally {
      setBusy(false)
    }
  }

  if (done) {
    return (
      <>
        <PageHeader title="Student registered" description="The face profile is encrypted and stored. They can be recognised from now on." />
        <div className="sheet max-w-2xl p-5">
          <p className="text-xl font-bold">{done.student.full_name}</p>
          <p className="text-muted">
            {done.student.prn}, {done.student.branch} year {done.student.year} division {done.student.division}, roll {done.student.roll_no}
          </p>
          <p className="mt-3 text-sm">
            {done.embeddings_stored} face templates saved, enrolled in {done.courses_enrolled} course{done.courses_enrolled === 1 ? '' : 's'}.
          </p>
          {done.temp_password && (
            <div className="mt-4 rounded-xl border border-late/50 bg-late/10 p-3 text-sm">
              <p className="font-bold">One-time password for the student portal</p>
              <p className="mt-1">
                Username <span className="font-bold">{done.username}</span>, password{' '}
                <span className="tnum font-bold">{done.temp_password}</span>
                <button className="ml-2 inline-flex items-center gap-1 text-ink hover:underline" onClick={() => navigator.clipboard?.writeText(done.temp_password)}>
                  <Copy size={13} /> Copy
                </button>
              </p>
              <p className="mt-1 text-muted">It is shown only once. The student must change it at first sign-in.</p>
            </div>
          )}
          <div className="mt-5 flex gap-2">
            <button
              className="btn btn-primary"
              onClick={() => {
                setDone(null)
                setForm(EMPTY)
                setConsent(false)
                setPhotos([])
              }}
            >
              Register another student
            </button>
            <Link className="btn btn-quiet" to="/students">
              All students
            </Link>
          </div>
        </div>
      </>
    )
  }

  return (
    <>
      <PageHeader
        title="Register a student"
        description={`Enter the details, then take ${config.min_photos} to ${config.max_photos} photos from different angles. Each photo is checked for blur, light and a single clear face as you go.`}
      />
      <form onSubmit={submit} className="space-y-8">
        <section className="sheet p-5">
          <h2 className="mb-4 text-lg">Details</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Full name">{(id) => <input id={id} className="input" required minLength={2} value={form.name} onChange={set('name')} />}</Field>
            <Field label="PRN" hint="Permanent registration number, letters and digits">
              {(id) => <input id={id} className="input uppercase" required pattern="[A-Za-z0-9]{6,20}" value={form.prn} onChange={set('prn')} />}
            </Field>
            <Field label="E-mail">{(id) => <input id={id} type="email" className="input" required value={form.email} onChange={set('email')} />}</Field>
            <Field label="Phone">{(id) => <input id={id} type="tel" className="input" required pattern="\+?[0-9]{10,14}" value={form.phone} onChange={set('phone')} />}</Field>
            <Field label="Branch">
              {(id) => (
                <select id={id} className="input" value={form.branch} onChange={set('branch')}>
                  {(academic.length ? academic : [{ code: 'CS', name: 'Computer Engineering' }]).map((b) => (
                    <option key={b.code} value={b.code}>
                      {b.code} {b.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <div className="grid grid-cols-3 gap-3">
              <Field label="Year">
                {(id) => (
                  <select id={id} className="input" value={form.year} onChange={set('year')}>
                    {[1, 2, 3, 4].map((y) => (
                      <option key={y}>{y}</option>
                    ))}
                  </select>
                )}
              </Field>
              <Field label="Division">
                {(id) => (
                  <select id={id} className="input" value={form.division} onChange={set('division')}>
                    {divisions.map((d) => (
                      <option key={d}>{d}</option>
                    ))}
                  </select>
                )}
              </Field>
              <Field label="Roll no">{(id) => <input id={id} type="number" min="1" max="300" className="input" required value={form.roll_no} onChange={set('roll_no')} />}</Field>
            </div>
            <Field label="Portal password (optional)" hint="Leave empty to generate a one-time password">
              {(id) => <input id={id} type="password" className="input" autoComplete="new-password" minLength={8} value={form.password} onChange={set('password')} />}
            </Field>
          </div>
        </section>

        <section>
          <h2 className="mb-3 text-lg">Face photos</h2>
          <PhotoCapture cam={cam} photos={photos} setPhotos={setPhotos} max={config.max_photos} />
        </section>

        <section className="sheet p-5">
          <label className="flex items-start gap-3">
            <input type="checkbox" className="mt-1 h-4 w-4 accent-[rgb(var(--ink))]" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span className="max-w-prose text-sm">
              <span className="font-bold">The student agrees to the use of their face for attendance.</span>{' '}
              Photos are converted into encrypted face templates; the photos themselves are not kept. The student can
              ask for every trace to be erased at any time from their portal.
            </span>
          </label>
          <ErrorNote error={error} className="mt-4" />
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button className="btn btn-primary" disabled={busy}>
              {busy ? 'Registering…' : 'Register student'}
            </button>
            <span className="text-sm text-muted">
              {usable.length} usable photo{usable.length === 1 ? '' : 's'}, {config.min_photos} needed
            </span>
          </div>
        </section>
      </form>
    </>
  )
}
