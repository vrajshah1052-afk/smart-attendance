import { Link } from 'react-router-dom'
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Cpu, ScanFace, Timer, UserPlus } from 'lucide-react'
import { api } from '../api/client'
import { Chip, Empty, ErrorNote, Ledger, SessionStatus, Spinner } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'
import { useApi } from '../hooks/useApi'

const ENGINE_LABEL = {
  insightface: 'ArcFace',
  arcface_onnx: 'ArcFace',
  face_recognition: 'dlib ResNet',
  opencv: 'OpenCV LBP',
}

function firstName(full) {
  const words = (full || '').split(/\s+/).filter((w) => w && !/^(dr|prof|mr|mrs|ms)\.?$/i.test(w))
  return words[0] || ''
}

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

export default function Dashboard() {
  const { user } = useAuth()
  const { colors } = useTheme()
  const summary = useApi(() => api.get('/analytics/summary'), [])
  const today = useApi(() => api.get('/analytics/today'), [])
  const trend = useApi(() => api.get('/analytics/daily-trend', { days: 21 }), [])
  const s = summary.data
  const threshold = s?.shortage_threshold ?? 75
  const engine = s?.engine
  const dateLine = new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })

  return (
    <>
      <section className="sheet glow-border relative mb-8 overflow-hidden p-6 sm:p-8">
        <div className="absolute -right-16 -top-24 h-72 w-72 rounded-full bg-glow1/25 blur-3xl" aria-hidden="true" />
        <div className="absolute -bottom-28 right-48 h-60 w-60 rounded-full bg-glow2/20 blur-3xl" aria-hidden="true" />
        <div className="relative flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="eyebrow">{dateLine}</p>
            <h1 className="mt-2 text-[30px] font-bold leading-tight sm:text-[40px]">
              <span className="text-gradient">{greeting()},</span> <span className="text-aurora">{firstName(user?.full_name)}</span>
            </h1>
            <p className="mt-2 max-w-prose text-muted">Today&apos;s classes and where attendance stands.</p>
            {engine && (
              <div className="mt-4 flex flex-wrap gap-2">
                <Chip tone={engine.status === 'ready' ? 'ink' : 'late'}>
                  <Cpu size={13} /> {ENGINE_LABEL[engine.name] || engine.name || 'Face engine'} {engine.status === 'ready' ? 'ready' : engine.status}
                </Chip>
                <Chip>
                  {engine.index?.embeddings ?? 0} face templates · {engine.index?.students ?? 0} students
                </Chip>
                <Chip>match ≥ {engine.threshold ?? '–'}</Chip>
              </div>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/attendance/group" className="btn btn-primary">
              <ScanFace size={17} /> Take attendance
            </Link>
            <Link to="/attendance/late" className="btn btn-quiet">
              <Timer size={17} /> Late entry
            </Link>
            <Link to="/students/register" className="btn btn-quiet">
              <UserPlus size={17} /> Register student
            </Link>
          </div>
        </div>
      </section>

      <ErrorNote error={summary.error} className="mb-4" />
      {summary.loading && !s ? (
        <Spinner />
      ) : (
        s && (
          <Ledger
            items={[
              { label: 'Students', value: s.students },
              { label: 'Faces enrolled', value: s.enrolled_faces, tone: 'ink' },
              { label: 'Sessions today', value: s.sessions_today },
              { label: 'Average attendance', value: s.overall_attendance_pct != null ? `${s.overall_attendance_pct}%` : '–' },
              { label: `Below ${threshold}%`, value: s.shortage_students, tone: s.shortage_students ? 'absent' : undefined },
              { label: 'Matches to review', value: s.pending_reviews, tone: s.pending_reviews ? 'late' : undefined },
              { label: 'Spoof attempts today', value: s.spoof_today, tone: s.spoof_today ? 'spoof' : undefined },
            ]}
          />
        )
      )}

      <div className="mt-8 grid gap-8 xl:grid-cols-[1.25fr_1fr]">
        <section>
          <h2 className="mb-3 text-lg">Today&apos;s sessions</h2>
          <div className="sheet overflow-x-auto">
            {today.loading ? (
              <Spinner className="p-4" />
            ) : !today.data?.length ? (
              <Empty title="No sessions scheduled today" action={<Link className="btn btn-quiet btn-sm" to="/sessions">Plan a session</Link>}>
                Start one from the attendance page or schedule it on the Sessions page.
              </Empty>
            ) : (
              <table className="register min-w-[560px]">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Course</th>
                    <th>Status</th>
                    <th className="text-right">Present</th>
                    <th className="text-right">Late</th>
                    <th className="text-right">Absent</th>
                  </tr>
                </thead>
                <tbody>
                  {today.data.map((x) => (
                    <tr key={x.session_id}>
                      <td className="tnum whitespace-nowrap">
                        {x.start_time}–{x.end_time}
                      </td>
                      <td>
                        <span className="font-semibold">{x.course_code}</span> <span className="text-muted">{x.course_name}</span>
                        {x.teacher_name && <div className="text-xs text-muted">{x.teacher_name}</div>}
                      </td>
                      <td>
                        <SessionStatus status={x.status} />
                      </td>
                      <td className="tnum text-right font-semibold text-ink">{x.present_count}</td>
                      <td className="tnum text-right font-semibold text-late">{x.late_count}</td>
                      <td className="tnum text-right font-semibold text-absent">{x.absent_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>

        <section>
          <h2 className="mb-3 text-lg">Attendance over the last three weeks</h2>
          <div className="sheet h-72 p-4">
            {trend.data?.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trend.data} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
                  <defs>
                    <linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={colors.ink} stopOpacity={0.45} />
                      <stop offset="100%" stopColor={colors.ink} stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="trend-stroke" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor={colors.glow1} />
                      <stop offset="55%" stopColor={colors.ink} />
                      <stop offset="100%" stopColor={colors.glow2} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={colors.line} strokeDasharray="3 6" vertical={false} />
                  <XAxis dataKey="day" tick={{ fill: colors.muted, fontSize: 11 }} tickFormatter={(d) => d.slice(5)} stroke={colors.line} />
                  <YAxis domain={[0, 100]} tick={{ fill: colors.muted, fontSize: 11 }} stroke={colors.line} />
                  <Tooltip
                    contentStyle={{ background: colors.panel, border: `1px solid ${colors.line}`, color: colors.fg, borderRadius: 12 }}
                    formatter={(v) => [`${v}%`, 'Attendance']}
                  />
                  <ReferenceLine y={threshold} stroke={colors.absent} strokeDasharray="4 4" />
                  <Area
                    type="monotone"
                    dataKey="pct"
                    stroke="url(#trend-stroke)"
                    strokeWidth={2.6}
                    fill="url(#trend-fill)"
                    dot={{ r: 3, fill: colors.panel, stroke: colors.ink, strokeWidth: 2 }}
                    activeDot={{ r: 5, fill: colors.ink }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <Empty title="No closed sessions yet">The trend appears once sessions are closed.</Empty>
            )}
          </div>
        </section>
      </div>
    </>
  )
}
