import { useMemo } from 'react'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function shade(pct, colors) {
  if (pct === null || pct === undefined) return colors.panel2
  // red ink below 60%, amber 60-75, blue ink above; opacity encodes strength
  if (pct < 60) return colors.absent.replace('rgb', 'rgba').replace(')', `,${0.35 + (60 - pct) / 120})`)
  if (pct < 75) return colors.late.replace('rgb', 'rgba').replace(')', ',0.7)')
  return colors.ink.replace('rgb', 'rgba').replace(')', `,${0.25 + ((pct - 75) / 25) * 0.75})`)
}

/** Calendar heatmap: columns are weeks, rows are weekdays. */
export function CalendarHeatmap({ data, weeks = 12, colors }) {
  const cells = useMemo(() => {
    const byDay = Object.fromEntries((data || []).map((d) => [d.day, d]))
    const today = new Date()
    const start = new Date(today)
    start.setDate(today.getDate() - ((today.getDay() + 6) % 7) - (weeks - 1) * 7)
    const out = []
    for (let w = 0; w < weeks; w += 1) {
      for (let d = 0; d < 7; d += 1) {
        const date = new Date(start)
        date.setDate(start.getDate() + w * 7 + d)
        const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
        out.push({ w, d, key, info: byDay[key], future: date > today })
      }
    }
    return out
  }, [data, weeks])

  return (
    <div className="overflow-x-auto">
      <div className="inline-grid gap-1" style={{ gridTemplateColumns: `auto repeat(${weeks}, 16px)`, gridTemplateRows: 'repeat(7, 16px)' }}>
        {DAYS.map((d, i) => (
          <span key={d} className="pr-2 text-[11px] leading-4 text-muted" style={{ gridColumn: 1, gridRow: i + 1 }}>
            {i % 2 === 0 ? d : ''}
          </span>
        ))}
        {cells.map((c) => (
          <span
            key={c.key}
            title={c.info ? `${c.key}: ${c.info.pct ?? '–'}% over ${c.info.sessions} lecture(s)` : `${c.key}: no lectures`}
            className="rounded-[3px]"
            style={{
              gridColumn: c.w + 2,
              gridRow: c.d + 1,
              background: c.future ? 'transparent' : shade(c.info?.pct, colors),
              border: c.future ? `1px dashed ${colors.line}` : 'none',
            }}
          />
        ))}
      </div>
    </div>
  )
}

/** Weekday x start-hour grid of average attendance. */
export function SlotHeatmap({ data, colors }) {
  const hours = useMemo(() => [...new Set((data || []).map((d) => d.hour))].sort((a, b) => a - b), [data])
  const lookup = useMemo(() => Object.fromEntries((data || []).map((d) => [`${d.weekday}-${d.hour}`, d])), [data])
  if (!hours.length) return <p className="text-sm text-muted">No closed lectures yet.</p>
  return (
    <div className="overflow-x-auto">
      <table className="text-xs">
        <thead>
          <tr>
            <th />
            {hours.map((h) => (
              <th key={h} className="tnum px-1 pb-1 font-normal text-muted">
                {String(h).padStart(2, '0')}:00
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {DAYS.slice(0, 6).map((day, wd) => (
            <tr key={day}>
              <td className="pr-2 text-muted">{day}</td>
              {hours.map((h) => {
                const cell = lookup[`${wd}-${h}`]
                return (
                  <td key={h} className="p-0.5">
                    <div
                      className="tnum flex h-8 w-12 items-center justify-center rounded-[3px] font-bold"
                      style={{ background: shade(cell?.pct, colors), color: cell ? colors.fg : 'transparent' }}
                      title={cell ? `${day} ${h}:00, ${cell.pct}% over ${cell.sessions} lecture(s)` : ''}
                    >
                      {cell?.pct != null ? Math.round(cell.pct) : ''}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
