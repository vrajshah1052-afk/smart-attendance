import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Clock, ScanFace, UserRound } from 'lucide-react'
import { api } from '../api/client'
import { Aurora } from '../components/Aurora'
import { PhotoCapture } from '../components/PhotoCapture'
import { ErrorNote, Field, Spinner } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useWebcam } from '../hooks/useWebcam'

// Public sign-up: anyone can create their own student account from the login page.
// The account waits in PENDING_APPROVAL until an admin approves it; only then can
// the student sign in and join the courses they want with a class code.

const EMPTY = {
  name: '',
  prn: '',
  email: '',
  phone: '',
  branch: '',
  year: '',
  division: '',
  roll_no: '',
  password: '',
  confirm: '',
}

function Shell({ children }) {
  const { user } = useAuth()
  return (
    <div className="relative min-h-screen px-4 pb-16 pt-5 sm:px-8">
      <Aurora />
      <header className="mx-auto flex max-w-3xl items-center justify-between gap-3">
        <Link to="/login" className="flex items-center gap-2.5">
          <span className="relative">
            <span className="absolute inset-0 rounded-[10px] bg-glow1 opacity-60 blur-md" />
            <img src="/favicon.svg" alt="" width="34" height="34" className="relative" />
          </span>
          <span className="font-display font-bold tracking-tight">
            Smart <span className="text-aurora">Attendance</span>
          </span>
        </Link>
        {user ? (
          <Link to="/" className="btn btn-quiet btn-sm">
            <UserRound size={15} /> {user.full_name?.split(' ')[0] || user.username}
          </Link>
        ) : (
          <Link to="/login" className="btn btn-quiet btn-sm">
            Sign in
          </Link>
        )}
      </header>
      <main className="mx-auto mt-8 max-w-3xl animate-fade-up">{children}</main>
    </div>
  )
}

function Done({ result }) {
  return (
    <section className="sheet glow-border p-7 text-center">
      <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-glow3 via-ink to-late text-white shadow-[0_12px_36px_-10px_rgb(var(--glow3))]">
        <Clock size={32} strokeWidth={3} />
      </span>
      <h2 className="mt-5 text-[26px] font-bold">{result.pending_approval ? 'Waiting for approval' : 'Account ready'}</h2>
      <p className="mx-auto mt-2 max-w-prose text-muted">{result.message}</p>
      <dl className="mx-auto mt-5 max-w-xs space-y-1 rounded-2xl border border-line/70 bg-panel2/60 px-5 py-4 text-sm">
        <div className="flex items-center justify-between gap-4">
          <dt className="text-muted">Your PRN</dt>
          <dd className="font-display text-lg font-bold tracking-wider text-ink">{result.prn}</dd>
        </div>
        <div className="flex items-center justify-between gap-4">
          <dt className="text-muted">Face templates</dt>
          <dd className="font-semibold">{result.embeddings_stored}</dd>
        </div>
      </dl>
      <p className="mx-auto mt-5 max-w-prose text-sm text-muted">
        {result.pending_approval
          ? 'An admin checks that you belong to this division and approves you. After that, sign in with your PRN and the password you chose, then join your classes with the 6-character class code your teacher gives out.'
          : 'Sign in with your PRN and the password you chose.'}
      </p>
      <Link to="/login" className="btn btn-primary mt-6 px-6 py-3">
        Go to sign in <ArrowRight size={17} />
      </Link>
    </section>
  )
}

export default function Signup() {
  const cam = useWebcam({ width: 1280, height: 960 })
  const [options, setOptions] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [step, setStep] = useState('details')
  const [form, setForm] = useState(EMPTY)
  const [photos, setPhotos] = useState([])
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  useEffect(() => {
    api.get('/signup').then(setOptions).catch(setLoadError)
  }, [])

  const branch = useMemo(() => options?.branches?.find((b) => b.code === form.branch), [options, form.branch])
  const years = useMemo(() => Object.keys(branch?.years || {}), [branch])
  const divisions = useMemo(() => branch?.years?.[String(form.year)] || [], [branch, form.year])

  // keep branch / year / division a valid combination as the selects above them change
  useEffect(() => {
    if (!options?.branches?.length) return
    setForm((f) => {
      const b = options.branches.find((x) => x.code === f.branch) || options.branches[0]
      const ys = Object.keys(b.years)
      const year = ys.includes(String(f.year)) ? String(f.year) : ys[0] || ''
      const ds = b.years[year] || []
      const division = ds.includes(f.division) ? f.division : ds[0] || ''
      if (b.code === f.branch && year === f.year && division === f.division) return f
      return { ...f, branch: b.code, year, division }
    })
  }, [options, form.branch, form.year, form.division])

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const usable = photos.filter((p) => p.result?.accepted)

  if (loadError) {
    return (
      <Shell>
        <ErrorNote error={loadError} />
      </Shell>
    )
  }
  if (!options) {
    return (
      <Shell>
        <Spinner />
      </Shell>
    )
  }
  if (!options.enabled) {
    return (
      <Shell>
        <p className="sheet p-6 text-center text-sm text-muted">
          Signing up yourself is turned off. Ask your teacher to register you.
        </p>
      </Shell>
    )
  }
  if (result) {
    return (
      <Shell>
        <Done result={result} />
      </Shell>
    )
  }

  const toPhotos = (e) => {
    e.preventDefault()
    if (form.password !== form.confirm) {
      setError('The two passwords do not match.')
      return
    }
    setError(null)
    setStep('photos')
  }

  const submit = async () => {
    setError(null)
    if (!consent) {
      setError('Tick the box to agree to face recognition for attendance.')
      return
    }
    if (usable.length < options.min_photos) {
      setError(`Take at least ${options.min_photos} good photos.`)
      return
    }
    setBusy(true)
    try {
      const data = new FormData()
      data.append('name', form.name.trim())
      data.append('prn', form.prn.trim().toUpperCase())
      data.append('email', form.email.trim())
      data.append('phone', form.phone.trim())
      data.append('branch', form.branch)
      data.append('year', String(form.year))
      data.append('division', form.division)
      data.append('roll_no', String(form.roll_no))
      data.append('password', form.password)
      data.append('consent', 'true')
      usable.slice(0, options.max_photos).forEach((p, i) => data.append('photos', p.blob, `photo${i}.jpg`))
      const res = await api.form('/signup', data)
      cam.stop()
      setResult(res)
    } catch (err) {
      setError(err)
      if (['PRN_EXISTS', 'EMAIL_EXISTS', 'ROLL_EXISTS', 'UNKNOWN_DIVISION', 'VALIDATION_ERROR'].includes(err.code)) {
        setStep('details')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Shell>
      <section className="sheet glow-border p-6 sm:p-8">
        <h1 className="flex items-center gap-2.5 text-[28px] font-bold">
          <ScanFace size={26} className="text-ink" /> Create your student account
        </h1>
        <p className="mt-1 max-w-prose text-sm text-muted">
          Fill in your details, then take a few selfies. An admin approves you before you can sign in; after that you
          join your classes yourself with a class code.
        </p>

        {step === 'details' ? (
          <form onSubmit={toPhotos} className="mt-6 space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Full name">
                {(id) => (
                  <input id={id} className="input" autoComplete="name" required minLength={2} value={form.name} onChange={set('name')} />
                )}
              </Field>
              <Field label="PRN" hint="Your college registration number">
                {(id) => (
                  <input id={id} className="input uppercase" required pattern="[A-Za-z0-9]{6,20}" value={form.prn} onChange={set('prn')} />
                )}
              </Field>
              <Field label="College e-mail">
                {(id) => <input id={id} type="email" className="input" autoComplete="email" required value={form.email} onChange={set('email')} />}
              </Field>
              <Field label="Phone">
                {(id) => (
                  <input id={id} type="tel" className="input" autoComplete="tel" required pattern="[+]?[0-9]{10,14}" value={form.phone} onChange={set('phone')} />
                )}
              </Field>
              <Field label="Branch">
                {(id) => (
                  <select id={id} className="input" required value={form.branch} onChange={set('branch')}>
                    {options.branches.map((b) => (
                      <option key={b.code} value={b.code}>
                        {b.code} - {b.name}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
              <div className="grid grid-cols-3 gap-3">
                <Field label="Year">
                  {(id) => (
                    <select id={id} className="input" required value={form.year} onChange={set('year')}>
                      {years.map((y) => (
                        <option key={y} value={y}>
                          {y}
                        </option>
                      ))}
                    </select>
                  )}
                </Field>
                <Field label="Division">
                  {(id) => (
                    <select id={id} className="input" required value={form.division} onChange={set('division')}>
                      {divisions.map((d) => (
                        <option key={d}>{d}</option>
                      ))}
                    </select>
                  )}
                </Field>
                <Field label="Roll no">
                  {(id) => (
                    <input id={id} type="number" min="1" max="300" className="input" required value={form.roll_no} onChange={set('roll_no')} />
                  )}
                </Field>
              </div>
              <Field label="Choose a password" hint="At least 8 characters with a letter and a digit">
                {(id) => (
                  <input
                    id={id}
                    type="password"
                    className="input"
                    autoComplete="new-password"
                    required
                    minLength={8}
                    value={form.password}
                    onChange={set('password')}
                  />
                )}
              </Field>
              <Field label="Repeat the password">
                {(id) => (
                  <input
                    id={id}
                    type="password"
                    className="input"
                    autoComplete="new-password"
                    required
                    minLength={8}
                    value={form.confirm}
                    onChange={set('confirm')}
                  />
                )}
              </Field>
            </div>
            <ErrorNote error={error} />
            <button className="btn btn-primary w-full py-3">
              Next: face photos <ArrowRight size={17} />
            </button>
            <p className="text-center text-xs text-muted">
              Already have an account?{' '}
              <Link to="/login" className="font-semibold text-ink hover:underline">
                Sign in
              </Link>
            </p>
          </form>
        ) : (
          <div className="mt-6 space-y-5">
            <button type="button" className="flex items-center gap-1 text-sm text-muted hover:text-fg" onClick={() => setStep('details')}>
              <ArrowLeft size={15} /> Back to your details
            </button>
            <p className="text-sm text-muted">
              Take {options.min_photos} to {options.max_photos} photos in good light and follow the prompts. Turning
              your head left and right helps the camera know you from every angle.
            </p>
            <PhotoCapture cam={cam} photos={photos} setPhotos={setPhotos} max={options.max_photos} checkPath="/signup/quality-check" />
            <label className="flex items-start gap-3 rounded-2xl border border-line/70 bg-panel2/50 p-4">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 accent-[rgb(var(--ink))]"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
              />
              <span className="text-sm">
                <span className="font-bold">I agree to face recognition for attendance.</span> My photos become
                encrypted face templates and are not kept. I can erase everything from my portal at any time.
              </span>
            </label>
            <ErrorNote error={error} />
            <button type="button" className="btn btn-primary w-full py-3" disabled={busy} onClick={submit}>
              {busy ? 'Creating your account...' : `Create account (${usable.length}/${options.min_photos} photos)`}
            </button>
          </div>
        )}
      </section>
    </Shell>
  )
}
