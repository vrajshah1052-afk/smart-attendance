import { useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowRight, AtSign, Database, Eye, EyeOff, KeyRound, Lock, QrCode, ScanFace, ShieldCheck, Sparkles, UserPlus } from 'lucide-react'
import { Aurora } from '../components/Aurora'
import { ErrorNote, Mark } from '../components/ui'
import { useAuth } from '../context/AuthContext'

// A slice of a paper register: what this product replaces.
const SAMPLE = [
  { roll: 1, name: 'Aarav Patil', marks: ['PRESENT', 'PRESENT', 'LATE', 'PRESENT'] },
  { roll: 2, name: 'Aditi Kulkarni', marks: ['PRESENT', 'PRESENT', 'PRESENT', 'PRESENT'] },
  { roll: 3, name: 'Rohan Joshi', marks: ['ABSENT', 'PRESENT', 'PRESENT', 'LATE'] },
  { roll: 4, name: 'Sneha Deshpande', marks: ['PRESENT', 'ABSENT', 'PRESENT', 'PRESENT'] },
]

const FEATURES = [
  { icon: ScanFace, text: 'Whole class from one photo' },
  { icon: ShieldCheck, text: 'Blink and head-turn liveness' },
  { icon: Lock, text: 'AES-encrypted face templates' },
  { icon: Database, text: 'MySQL + MongoDB' },
]

// face-mesh outline for the scanner illustration (viewBox 220 x 260)
const MESH = [
  [[60, 80], [80, 58], [110, 50], [140, 58], [160, 80]],
  [[60, 80], [52, 105], [54, 135], [60, 162], [72, 186], [90, 205], [110, 212], [130, 205], [148, 186], [160, 162], [166, 135], [168, 105], [160, 80]],
  [[70, 92], [88, 86], [104, 90]],
  [[116, 90], [132, 86], [150, 92]],
  [[110, 96], [110, 128], [100, 145], [110, 149], [120, 145], [110, 128]],
  [[90, 172], [110, 166], [130, 172], [110, 180], [90, 172]],
  [[52, 105], [70, 92]], [[168, 105], [150, 92]], [[72, 186], [90, 172]], [[148, 186], [130, 172]],
  [[100, 145], [90, 172]], [[120, 145], [130, 172]], [[54, 135], [100, 145]], [[166, 135], [120, 145]],
  [[110, 50], [110, 96]], [[80, 58], [88, 86]], [[140, 58], [132, 86]], [[110, 180], [110, 212]],
]
const DOTS = [...new Map(MESH.flat().map((p) => [p.join(','), p])).values()]
const BRACKETS = ['M14 46V22a8 8 0 0 1 8-8h24', 'M174 14h24a8 8 0 0 1 8 8v24', 'M206 214v24a8 8 0 0 1-8 8h-24', 'M46 246H22a8 8 0 0 1-8-8v-24']

function FaceScan() {
  return (
    <div className="relative mx-auto w-[250px] animate-float" aria-hidden="true">
      <div className="absolute inset-8 rounded-full bg-glow1/40 blur-3xl" />
      <div className="sheet glow-border relative overflow-hidden rounded-[28px] p-4">
        <svg viewBox="0 0 220 260" className="w-full">
          <defs>
            <linearGradient id="fs-stroke" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" style={{ stopColor: 'rgb(var(--glow2))' }} />
              <stop offset="1" style={{ stopColor: 'rgb(var(--glow3))' }} />
            </linearGradient>
            <linearGradient id="fs-beam" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" style={{ stopColor: 'rgb(var(--glow2))', stopOpacity: 0 }} />
              <stop offset="1" style={{ stopColor: 'rgb(var(--glow2))', stopOpacity: 0.5 }} />
            </linearGradient>
          </defs>
          {BRACKETS.map((d) => (
            <path key={d} d={d} fill="none" stroke="url(#fs-stroke)" strokeWidth="3" strokeLinecap="round" />
          ))}
          {MESH.map((line, i) => (
            <polyline key={i} points={line.map((p) => p.join(',')).join(' ')} fill="none" className="stroke-ink/40" strokeWidth="1" />
          ))}
          <ellipse cx="88" cy="108" rx="11" ry="5.5" fill="none" className="stroke-glow2" strokeWidth="1.6" />
          <ellipse cx="132" cy="108" rx="11" ry="5.5" fill="none" className="stroke-glow2" strokeWidth="1.6" />
          {DOTS.map(([x, y]) => (
            <circle key={`${x},${y}`} cx={x} cy={y} r="2.1" className="fill-ink" />
          ))}
          <g className="animate-scan">
            <rect x="20" y="16" width="180" height="28" fill="url(#fs-beam)" />
            <rect x="20" y="43" width="180" height="1.6" rx="1" className="fill-glow2" />
          </g>
        </svg>
        <div className="mt-3 flex items-center justify-between rounded-xl border border-line/70 bg-panel2/60 px-3 py-2 text-xs">
          <span className="flex items-center gap-2 font-semibold">
            <span className="h-2 w-2 rounded-full bg-glow2 shadow-[0_0_10px_rgb(var(--glow2))]" /> Aarav Patil
          </span>
          <span className="font-bold text-ink">Present · 0.92</span>
        </div>
      </div>
    </div>
  )
}

export default function Login() {
  const { user, login } = useAuth()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to={params.get('next') || (user.role === 'STUDENT' ? '/me' : '/')} replace />

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const u = await login(username.trim(), password)
      navigate(params.get('next') || (u.role === 'STUDENT' ? '/me' : '/'), { replace: true })
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative grid min-h-screen lg:grid-cols-[1.2fr_1fr]">
      <Aurora />
      <section className="flex flex-col justify-between gap-10 px-6 py-8 sm:px-12 lg:py-12">
        <div className="flex items-center gap-3">
          <span className="relative">
            <span className="absolute inset-0 rounded-[10px] bg-glow1 opacity-60 blur-md" />
            <img src="/favicon.svg" alt="" width="38" height="38" className="relative" />
          </span>
          <span className="font-display text-lg font-bold tracking-tight">
            Smart <span className="text-aurora">Attendance</span>
          </span>
        </div>

        <div className="grid items-center gap-10 xl:grid-cols-[1fr_auto]">
          <div className="max-w-xl animate-fade-up">
            <p className="glass inline-flex items-center gap-2 rounded-full border border-line/70 px-3 py-1 text-xs font-semibold text-muted">
              <Sparkles size={14} className="text-glow3" /> ArcFace recognition · VIT Pune
            </p>
            <h1 className="mt-5 text-[40px] font-bold leading-[1.05] sm:text-[56px]">
              Attendance at the <span className="text-aurora">speed of a glance.</span>
            </h1>
            <p className="mt-5 max-w-prose text-[16px] text-muted">
              Teachers photograph the class and confirm the names. Late arrivals check in at the door with a blink or a
              head turn. Students see their own record and how far they are from 75%.
            </p>
            <ul className="mt-6 flex flex-wrap gap-2">
              {FEATURES.map(({ icon: Icon, text }, i) => (
                <li
                  key={text}
                  className="glass flex animate-fade-up items-center gap-2 rounded-full border border-line/70 px-3 py-1.5 text-xs font-semibold"
                  style={{ animationDelay: `${150 + i * 70}ms` }}
                >
                  <Icon size={14} className="text-ink" /> {text}
                </li>
              ))}
            </ul>
          </div>
          <div className="hidden xl:block">
            <FaceScan />
          </div>
        </div>

        <div className="sheet max-w-xl overflow-x-auto p-1" aria-hidden="true">
          <p className="eyebrow px-3.5 pb-1 pt-3">This week&apos;s register</p>
          <table className="register">
            <thead>
              <tr>
                <th className="roll">Roll</th>
                <th>Name</th>
                {['Mon', 'Tue', 'Wed', 'Thu'].map((d) => (
                  <th key={d} className="text-center">
                    {d}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {SAMPLE.map((row, r) => (
                <tr key={row.roll}>
                  <td className="roll">{row.roll}</td>
                  <td className="whitespace-nowrap">{row.name}</td>
                  {row.marks.map((m, c) => (
                    <td key={c} className="text-center">
                      <Mark status={m} size={24} animate delay={350 + (c * SAMPLE.length + r) * 55} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="flex items-center justify-center px-6 pb-12 sm:px-12 lg:py-10">
        <form onSubmit={submit} className="sheet glow-border w-full max-w-md animate-fade-up p-7 sm:p-9" style={{ animationDelay: '120ms' }}>
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-glow1 via-ink to-glow3 text-white shadow-[0_10px_30px_-8px_rgb(var(--glow1))]">
            <ScanFace size={24} />
          </span>
          <h2 className="mt-5 text-[28px] font-bold">Welcome back</h2>
          <p className="mt-1 text-sm text-muted">
            Admins use their e-mail, teachers their 6-digit employee code, students their PRN.
          </p>
          <div className="mt-7 space-y-4">
            <div>
              <label className="label" htmlFor="username">
                E-mail, employee code or PRN
              </label>
              <div className="relative">
                <AtSign size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
                <input
                  id="username"
                  className="input pl-10"
                  autoComplete="username"
                  autoFocus
                  required
                  placeholder="you@college.edu, 100101 or 12310001"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </div>
            </div>
            <div>
              <label className="label" htmlFor="password">
                Password
              </label>
              <div className="relative">
                <KeyRound size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
                <input
                  id="password"
                  type={show ? 'text' : 'password'}
                  className="input px-10"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <button
                  type="button"
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-lg p-1.5 text-muted hover:text-fg"
                  onClick={() => setShow((s) => !s)}
                  aria-label={show ? 'Hide password' : 'Show password'}
                >
                  {show ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>
            <ErrorNote error={error} />
            {error?.code === 'PENDING_APPROVAL' && (
              <div className="rounded-xl border border-late/40 bg-late/10 p-3 text-sm">
                Your account exists but an admin has not approved it yet. Once they approve you under
                <span className="font-semibold"> Admin &rarr; Pending approvals</span>, sign in here again.
              </div>
            )}
            <button className="btn btn-primary group w-full py-3 text-[15px]" disabled={busy}>
              {busy ? 'Signing in…' : 'Sign in'}
              {!busy && <ArrowRight size={17} className="transition-transform group-hover:translate-x-0.5" />}
            </button>
          </div>
          <Link
            to="/signup"
            className="mt-4 flex items-center justify-between rounded-xl border border-line/70 bg-panel2/50 px-4 py-3 text-sm transition-colors hover:border-ink/50"
          >
            <span>
              <span className="font-semibold">New student? Sign up</span>{' '}
              <span className="text-muted">Register your face, an admin approves you</span>
            </span>
            <UserPlus size={18} className="text-ink" />
          </Link>
          <Link
            to="/join"
            className="mt-2 flex items-center justify-between rounded-xl border border-line/70 bg-panel2/50 px-4 py-3 text-sm transition-colors hover:border-ink/50"
          >
            <span>
              <span className="font-semibold">Got a class code?</span> <span className="text-muted">Join a class</span>
            </span>
            <QrCode size={18} className="text-ink" />
          </Link>
          <p className="mt-7 border-t border-line/60 pt-5 text-xs text-muted">
            Forgot your password? Your class teacher or the admin can reset it.
          </p>
        </form>
      </section>
    </div>
  )
}
