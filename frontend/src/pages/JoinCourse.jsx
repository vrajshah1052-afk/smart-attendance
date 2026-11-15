import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, BookOpen, Check, Clock, GraduationCap, KeyRound, ScanFace, Sparkles, UserRound, Users } from 'lucide-react'
import { api } from '../api/client'
import { Aurora } from '../components/Aurora'
import { PhotoCapture } from '../components/PhotoCapture'
import { Chip, ErrorNote, Field, Spinner, Tabs } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useWebcam } from '../hooks/useWebcam'

// Public landing page of a course QR / class code: /join/<code>.
// Students sign in and join, or sign up with their face and join in one go.

const cleanCode = (v) => (v || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6)

function Shell({ children }) {
  const { user } = useAuth()
  return (
    <div className="relative min-h-screen px-4 pb-16 pt-5 sm:px-8">
      <Aurora />
      <header className="mx-auto flex max-w-3xl items-center justify-between gap-3">
        <Link to="/" className="flex items-center gap-2.5">
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

function CodeEntry({ error }) {
  const navigate = useNavigate()
  const [code, setCode] = useState('')
  return (
    <form
      className="sheet glow-border mx-auto max-w-md p-7 text-center"
      onSubmit={(e) => {
        e.preventDefault()
        if (code.length === 6) navigate(`/join/${code}`)
      }}
    >
      <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-glow1 via-ink to-glow3 text-white shadow-[0_10px_30px_-8px_rgb(var(--glow1))]">
        <BookOpen size={22} />
      </span>
      <h1 className="mt-4 text-[28px] font-bold">Join a class</h1>
      <p className="mt-1 text-sm text-muted">Scan the QR code your teacher shows, or type the 6-character class code.</p>
      <input
        className="input mt-6 text-center font-display text-3xl font-bold uppercase tracking-[0.35em]"
        aria-label="Class code"
        autoFocus
        autoComplete="off"
        autoCapitalize="characters"
        placeholder="K7Q2MX"
        value={code}
        onChange={(e) => setCode(cleanCode(e.target.value))}
      />
      <ErrorNote error={error} className="mt-4 text-left" />
      <button className="btn btn-primary mt-5 w-full py-3" disabled={code.length !== 6}>
        Find my class <ArrowRight size={17} />
      </button>
    </form>
  )
}

function CourseCard({ info }) {
  const c = info.course
  return (
    <section className="sheet glow-border relative overflow-hidden p-6 sm:p-8">
      <div className="absolute -right-20 -top-24 h-64 w-64 rounded-full bg-glow1/25 blur-3xl" aria-hidden="true" />
      <div className="absolute -bottom-24 left-10 h-52 w-52 rounded-full bg-glow2/20 blur-3xl" aria-hidden="true" />
      <div className="relative">
        <p className="eyebrow flex items-center gap-1.5">
          <Sparkles size={13} className="text-glow3" /> You&apos;re invited to join
        </p>
        <h1 className="mt-2 text-[30px] font-bold leading-tight sm:text-[38px]">
          <span className="text-gradient">{c.name}</span>
        </h1>
        <div className="mt-3 flex flex-wrap gap-2">
          <Chip tone="ink">{c.code}</Chip>
          <Chip>{c.branch_name || c.branch}</Chip>
          <Chip>
            Year {c.year_of_study} · Semester {c.semester}
          </Chip>
          <Chip>{c.credits} credits</Chip>
        </div>
        <div className="mt-6 grid gap-4 sm:grid-cols-[1fr_auto] sm:items-end">
          <dl className="space-y-2 text-sm">
            {c.coordinator && (
              <div className="flex items-center gap-2">
                <GraduationCap size={16} className="text-ink" />
                <dt className="sr-only">Teacher</dt>
                <dd>{c.coordinator}</dd>
              </div>
            )}
            <div className="flex items-center gap-2">
              <Users size={16} className="text-ink" />
              <dt className="sr-only">Students</dt>
              <dd>
                {c.enrolled} student{c.enrolled === 1 ? '' : 's'} enrolled
              </dd>
            </div>
          </dl>
          <div className="rounded-2xl border border-line/70 bg-panel2/60 px-5 py-3 text-center">
            <p className="eyebrow">Class code</p>
            <p className="mt-1 font-display text-3xl font-bold tracking-[0.3em] text-ink">{info.join_code}</p>
          </div>
        </div>
      </div>
    </section>
  )
}

function Joined({ result }) {
  const c = result.course
  if (result.pending_approval) {
    return (
      <section className="sheet glow-border mt-6 p-7 text-center">
        <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-glow3 via-ink to-late text-white shadow-[0_12px_36px_-10px_rgb(var(--glow3))]">
          <Clock size={32} strokeWidth={3} />
        </span>
        <h2 className="mt-5 text-[26px] font-bold">Account created — pending approval</h2>
        <p className="mx-auto mt-2 max-w-prose text-muted">
          {result.message || 'Your account is ready and your face is registered, but it needs admin approval before you can login.'}
        </p>
        <p className="mx-auto mt-4 max-w-prose text-sm text-muted">
          Your teacher will review and approve your registration. Once approved, you can login with your PRN and password.
        </p>
      </section>
    )
  }
  return (
    <section className="sheet glow-border mt-6 p-7 text-center">
      <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-glow2 via-ink to-glow1 text-white shadow-[0_12px_36px_-10px_rgb(var(--glow2))]">
        <Check size={32} strokeWidth={3} />
      </span>
      <h2 className="mt-5 text-[26px] font-bold">
        {result.already_enrolled ? 'You are already in this class' : `You're in ${c.code}!`}
      </h2>
      <p className="mx-auto mt-2 max-w-prose text-muted">
        {result.newAccount
          ? 'Your account is ready and your face is registered, so the class camera will recognise you from the next lecture.'
          : result.already_enrolled
            ? `${c.name} is already in your attendance.`
            : `${c.name} now shows up in your attendance.`}
      </p>
      <Link to="/me" className="btn btn-primary mt-6 px-6 py-3">
        Open my attendance <ArrowRight size={17} />
      </Link>
    </section>
  )
}

function SignInJoin({ code, onJoined }) {
  const { login } = useAuth()
  const [prn, setPrn] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(prn.trim(), password)
      onJoined(await api.post(`/join/${code}`))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="PRN">
        {(id) => <input id={id} className="input uppercase" autoComplete="username" required value={prn} onChange={(e) => setPrn(e.target.value)} />}
      </Field>
      <Field label="Password">
        {(id) => (
          <input id={id} type="password" className="input" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        )}
      </Field>
      <ErrorNote error={error} />
      <button className="btn btn-primary w-full py-3" disabled={busy}>
        {busy ? 'Joining…' : 'Sign in and join'} {!busy && <ArrowRight size={17} />}
      </button>
    </form>
  )
}

const EMPTY = { name: '', prn: '', email: '', phone: '', division: '', roll_no: '', password: '', confirm: '' }

function SignUpJoin({ code, info, onJoined }) {
  const { adopt } = useAuth()
  const cam = useWebcam({ width: 1280, height: 960 })
  const [step, setStep] = useState('details')
  const [form, setForm] = useState({ ...EMPTY, division: info.divisions[0] || '' })
  const [photos, setPhotos] = useState([])
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const usable = photos.filter((p) => p.result?.accepted)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const toPhotos = (e) => {
    e.preventDefault()
    if (form.password !== form.confirm) return setError('The two passwords do not match.')
    setError(null)
    setStep('photos')
  }

  const submit = async () => {
    setError(null)
    if (!consent) return setError('Tick the box to agree to face recognition for attendance.')
    if (usable.length < info.min_photos) return setError(`Take at least ${info.min_photos} good photos.`)
    setBusy(true)
    try {
      const data = new FormData()
      Object.entries(form).forEach(([k, v]) => k !== 'confirm' && data.append(k, k === 'prn' ? v.trim().toUpperCase() : v.trim()))
      data.append('consent', 'true')
      usable.slice(0, info.max_photos).forEach((p, i) => data.append('photos', p.blob, `photo${i}.jpg`))
      const res = await api.form(`/join/${code}/register`, data)
      cam.stop()
      if (res.pending_approval) {
        onJoined({ course: res.course, joined: false, newAccount: true, pending_approval: true, message: res.message })
      } else {
        adopt(res)
        onJoined({ course: res.course, joined: true, newAccount: true })
      }
    } catch (err) {
      setError(err)
      if (['PRN_EXISTS', 'EMAIL_EXISTS', 'ROLL_EXISTS', 'UNKNOWN_DIVISION', 'VALIDATION_ERROR'].includes(err.code)) setStep('details')
    } finally {
      setBusy(false)
    }
  }

  if (step === 'details') {
    return (
      <form onSubmit={toPhotos} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Full name">{(id) => <input id={id} className="input" autoComplete="name" required minLength={2} value={form.name} onChange={set('name')} />}</Field>
          <Field label="PRN">{(id) => <input id={id} className="input uppercase" required pattern="[A-Za-z0-9]{6,20}" value={form.prn} onChange={set('prn')} />}</Field>
          <Field label="College e-mail">{(id) => <input id={id} type="email" className="input" autoComplete="email" required value={form.email} onChange={set('email')} />}</Field>
          <Field label="Phone">{(id) => <input id={id} type="tel" className="input" autoComplete="tel" required pattern="\+?[0-9]{10,14}" value={form.phone} onChange={set('phone')} />}</Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Division">
              {(id) => (
                <select id={id} className="input" required value={form.division} onChange={set('division')}>
                  {info.divisions.map((d) => (
                    <option key={d}>{d}</option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Roll no">{(id) => <input id={id} type="number" min="1" max="300" className="input" required value={form.roll_no} onChange={set('roll_no')} />}</Field>
          </div>
          <div className="hidden sm:block" />
          <Field label="Choose a password" hint="At least 8 characters with a letter and a digit">
            {(id) => <input id={id} type="password" className="input" autoComplete="new-password" required minLength={8} value={form.password} onChange={set('password')} />}
          </Field>
          <Field label="Repeat the password">
            {(id) => <input id={id} type="password" className="input" autoComplete="new-password" required minLength={8} value={form.confirm} onChange={set('confirm')} />}
          </Field>
        </div>
        <ErrorNote error={error} />
        <button className="btn btn-primary w-full py-3">
          Next: face photos <ArrowRight size={17} />
        </button>
      </form>
    )
  }

  return (
    <div className="space-y-5">
      <button type="button" className="flex items-center gap-1 text-sm text-muted hover:text-fg" onClick={() => setStep('details')}>
        <ArrowLeft size={15} /> Back to your details
      </button>
      <p className="text-sm text-muted">
        Take {info.min_photos} to {info.max_photos} photos in good light and follow the prompts. Turning your head left
        and right helps the camera know you from every angle.
      </p>
      <PhotoCapture cam={cam} photos={photos} setPhotos={setPhotos} max={info.max_photos} checkPath={`/join/${code}/quality-check`} />
      <label className="flex items-start gap-3 rounded-2xl border border-line/70 bg-panel2/50 p-4">
        <input type="checkbox" className="mt-1 h-4 w-4 accent-[rgb(var(--ink))]" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
        <span className="text-sm">
          <span className="font-bold">I agree to face recognition for attendance.</span> My photos become encrypted face
          templates and are not kept. I can erase everything from my portal at any time.
        </span>
      </label>
      <ErrorNote error={error} />
      <button type="button" className="btn btn-primary w-full py-3" disabled={busy} onClick={submit}>
        {busy ? 'Creating your account…' : `Create account and join (${usable.length}/${info.min_photos} photos)`}
      </button>
    </div>
  )
}

export default function JoinCourse() {
  const { code: param } = useParams()
  const code = cleanCode(param)
  const { user } = useAuth()
  const [info, setInfo] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(!!code)
  const [tab, setTab] = useState('signin')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!code) return
    setLoading(true)
    setError(null)
    setResult(null)
    api
      .get(`/join/${code}`)
      .then(setInfo)
      .catch(setError)
      .finally(() => setLoading(false))
  }, [code])

  if (!code || (error && !info)) {
    return (
      <Shell>
        <CodeEntry error={error} />
      </Shell>
    )
  }
  if (loading || !info) {
    return (
      <Shell>
        <Spinner />
      </Shell>
    )
  }

  const joinNow = async () => {
    setBusy(true)
    setError(null)
    try {
      setResult(await api.post(`/join/${code}`))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  let action
  if (result) {
    action = <Joined result={result} />
  } else if (!info.join_open) {
    action = (
      <p className="sheet mt-6 p-5 text-center text-sm text-muted">
        This class is not taking new students right now. Ask your teacher to open it.
      </p>
    )
  } else if (user?.role === 'STUDENT') {
    action = (
      <section className="sheet mt-6 p-6 text-center">
        <p className="text-muted">
          Signed in as <span className="font-semibold text-fg">{user.full_name}</span> ({user.prn})
        </p>
        <ErrorNote error={error} className="mt-3 text-left" />
        <button className="btn btn-primary mt-4 w-full py-3 text-[15px] sm:w-auto sm:px-10" disabled={busy} onClick={joinNow}>
          <BookOpen size={17} /> {busy ? 'Joining…' : `Join ${info.course.code}`}
        </button>
      </section>
    )
  } else if (user) {
    action = (
      <section className="sheet mt-6 p-5 text-sm text-muted">
        Students scan this code to join. You are signed in as staff.{' '}
        <Link to="/courses" className="font-semibold text-ink hover:underline">
          Back to courses
        </Link>
      </section>
    )
  } else {
    const tabs = [{ value: 'signin', label: 'I have an account' }]
    if (info.self_registration) tabs.push({ value: 'signup', label: "I'm new here" })
    action = (
      <section className="sheet mt-6 p-5 sm:p-7">
        <Tabs tabs={tabs} value={tab} onChange={setTab} />
        {tab === 'signup' && info.self_registration ? (
          <>
            <h2 className="flex items-center gap-2 text-lg">
              <ScanFace size={19} className="text-ink" /> Create your account
            </h2>
            <p className="mb-5 mt-1 text-sm text-muted">One minute: your details, then a few selfies so the class camera can mark you.</p>
            <SignUpJoin code={code} info={info} onJoined={setResult} />
          </>
        ) : (
          <>
            <h2 className="flex items-center gap-2 text-lg">
              <KeyRound size={18} className="text-ink" /> Sign in with your PRN
            </h2>
            <p className="mb-5 mt-1 text-sm text-muted">You join {info.course.code} right after signing in.</p>
            <SignInJoin code={code} onJoined={setResult} />
          </>
        )}
      </section>
    )
  }

  return (
    <Shell>
      <CourseCard info={info} />
      {action}
    </Shell>
  )
}
