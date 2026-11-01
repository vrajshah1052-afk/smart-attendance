import { useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '../api/client'
import { CalendarHeatmap, SlotHeatmap } from '../components/Heatmap'
import { Empty, ErrorNote, PageHeader, Pct, Tabs } from '../components/ui'
import { useTheme } from '../context/ThemeContext'
import { useApi } from '../hooks/useApi'

function ChartBox({ title, note, children, height = 260 }) {
  return (
    <section className="min-w-0">
      <h2 className="text-lg">{title}</h2>
      {note && <p className="mb-2 text-sm text-muted">{note}</p>}
      <div className="sheet p-3" style={{ height }}>
        {children}
      </div>
    </section>
  )
}

export default function Analytics() {
  const { colors } = useTheme()
  const [days, setDays] = useState(30)
  const trend = useApi(() => api.get('/analytics/daily-trend', { days }), [days])
  const courses = useApi(() => api.get('/analytics/course-wise'), [])
  const heat = useApi(() => api.get('/analytics/heatmap', { weeks: 12 }), [])
  const tb = useApi(() => api.get('/analytics/top-bottom', { limit: 5 }), [])
  const spoof = useApi(() => api.get('/analytics/spoof-per-day', { days }), [days])
  const recog = useApi(() => api.get('/analytics/recognition-stats', { days }), [days])
  const low = useApi(() => api.get('/analytics/low-confidence', { days }), [days])
  const [heatTab, setHeatTab] = useState('calendar')

  const axis = { tick: { fill: colors.muted, fontSize: 11 }, stroke: colors.line }
  const tooltip = { contentStyle: { background: colors.panel, border: `1px solid ${colors.line}`, color: colors.fg, borderRadius: 6 } }
  const spoofRows = (spoof.data || []).map((d) => ({ day: d.day, attempts: d.attempts }))

  return (
    <>
      <PageHeader
        title="Analytics"
        description="Attendance figures come from MySQL views; recognition and spoof figures from MongoDB aggregation pipelines."
        actions={
          <select className="input w-auto" value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period">
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        }
      />
      <ErrorNote error={trend.error || courses.error} className="mb-4" />

      <div className="grid gap-8 xl:grid-cols-2">
        <ChartBox title="Daily attendance" note="Share of students present or late in closed lectures">
          {trend.data?.length ? (
            <ResponsiveContainer>
              <LineChart data={trend.data} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
                <CartesianGrid stroke={colors.line} vertical={false} />
                <XAxis dataKey="day" {...axis} tickFormatter={(d) => d.slice(5)} />
                <YAxis domain={[0, 100]} {...axis} />
                <Tooltip {...tooltip} formatter={(v) => [`${v}%`, 'Attendance']} />
                <ReferenceLine y={75} stroke={colors.absent} strokeDasharray="4 4" label={{ value: '75%', fill: colors.absent, fontSize: 11, position: 'insideBottomRight' }} />
                <Line type="monotone" dataKey="pct" stroke={colors.ink} strokeWidth={2.2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <Empty title="No closed lectures in this period" />
          )}
        </ChartBox>

        <ChartBox title="Present, late and absent per day">
          {trend.data?.length ? (
            <ResponsiveContainer>
              <BarChart data={trend.data} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
                <CartesianGrid stroke={colors.line} vertical={false} />
                <XAxis dataKey="day" {...axis} tickFormatter={(d) => d.slice(5)} />
                <YAxis {...axis} allowDecimals={false} />
                <Tooltip {...tooltip} />
                <Legend wrapperStyle={{ fontSize: 12, color: colors.muted }} />
                <Bar dataKey="present" name="Present" stackId="a" fill={colors.ink} />
                <Bar dataKey="late" name="Late" stackId="a" fill={colors.late} />
                <Bar dataKey="absent" name="Absent" stackId="a" fill={colors.absent} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <Empty title="No data" />
          )}
        </ChartBox>

        <ChartBox title="By course" note="Average of students' attendance in each course (v_course_summary)">
          {courses.data?.length ? (
            <ResponsiveContainer>
              <BarChart data={courses.data} layout="vertical" margin={{ top: 4, right: 24, bottom: 0, left: 8 }}>
                <CartesianGrid stroke={colors.line} horizontal={false} />
                <XAxis type="number" domain={[0, 100]} {...axis} />
                <YAxis type="category" dataKey="code" width={70} {...axis} />
                <Tooltip {...tooltip} formatter={(v, n) => (n === 'avg_attendance_pct' ? [`${v}%`, 'Average'] : [v, n])} />
                <ReferenceLine x={75} stroke={colors.absent} strokeDasharray="4 4" />
                <Bar dataKey="avg_attendance_pct" fill={colors.ink} radius={[0, 3, 3, 0]} barSize={22} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <Empty title="No courses" />
          )}
        </ChartBox>

        <section className="min-w-0">
          <h2 className="text-lg">When attendance drops</h2>
          <Tabs
            value={heatTab}
            onChange={setHeatTab}
            tabs={[
              { value: 'calendar', label: 'Calendar' },
              { value: 'slots', label: 'Day and hour' },
            ]}
          />
          <div className="sheet p-4">
            {heatTab === 'calendar' ? (
              <CalendarHeatmap data={heat.data?.calendar} weeks={12} colors={colors} />
            ) : (
              <SlotHeatmap data={heat.data?.weekday_hour} colors={colors} />
            )}
            <p className="mt-3 text-xs text-muted">Blue: at or above 75%. Amber: 60 to 75%. Red: below 60%. Grey: no lectures.</p>
          </div>
        </section>

        <section className="min-w-0">
          <h2 className="mb-2 text-lg">Highest and lowest attendance</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {[
              ['Highest', tb.data?.top],
              ['Lowest', tb.data?.bottom],
            ].map(([label, rows]) => (
              <div key={label} className="sheet">
                <p className="border-b border-line px-4 py-2 text-sm font-bold">{label}</p>
                <ol className="text-sm">
                  {(rows || []).map((r) => (
                    <li key={r.prn} className="flex items-center justify-between gap-2 border-b border-line/60 px-4 py-2 last:border-0">
                      <span className="truncate">{r.full_name}</span>
                      <Pct value={r.attendance_pct} />
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        </section>

        <ChartBox title="Spoof attempts per day" note="Blocked liveness checks and suspected screen or photo captures">
          {spoofRows.length ? (
            <ResponsiveContainer>
              <BarChart data={spoofRows} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
                <CartesianGrid stroke={colors.line} vertical={false} />
                <XAxis dataKey="day" {...axis} tickFormatter={(d) => d.slice(5)} />
                <YAxis {...axis} allowDecimals={false} />
                <Tooltip {...tooltip} />
                <Bar dataKey="attempts" name="Attempts" fill={colors.spoof} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <Empty title="No spoof attempts in this period" />
          )}
        </ChartBox>

        <ChartBox title="Recognition results per day" note="Every detected face, from group photos, late entries and the live feed">
          {recog.data?.length ? (
            <ResponsiveContainer>
              <BarChart data={recog.data} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
                <CartesianGrid stroke={colors.line} vertical={false} />
                <XAxis dataKey="day" {...axis} tickFormatter={(d) => d.slice(5)} />
                <YAxis {...axis} allowDecimals={false} />
                <Tooltip {...tooltip} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="matched" name="Recognised" stackId="r" fill={colors.ink} />
                <Bar dataKey="low_confidence" name="Unsure" stackId="r" fill={colors.late} />
                <Bar dataKey="unknown" name="Unknown" stackId="r" fill={colors.absent} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <Empty title="No recognitions logged yet" />
          )}
        </ChartBox>

        <section className="min-w-0">
          <h2 className="text-lg">Students who are often hard to recognise</h2>
          <p className="mb-2 text-sm text-muted">Repeated matches near the threshold; consider updating their face photos.</p>
          <div className="sheet overflow-x-auto">
            {!low.data?.length ? (
              <Empty title="Nobody stands out" />
            ) : (
              <table className="register">
                <thead>
                  <tr>
                    <th>Student</th>
                    <th className="text-right">Times</th>
                    <th className="text-right">Average similarity</th>
                  </tr>
                </thead>
                <tbody>
                  {low.data.map((r) => (
                    <tr key={r.prn}>
                      <td>
                        {r.name || r.prn} <span className="text-xs text-muted">{r.prn}</span>
                      </td>
                      <td className="tnum text-right">{r.occurrences}</td>
                      <td className="tnum text-right">{r.avg_confidence}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </section>
      </div>
    </>
  )
}
