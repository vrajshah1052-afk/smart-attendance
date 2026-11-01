import { useCallback, useEffect, useRef, useState } from 'react'
import { Bell } from 'lucide-react'
import { api } from '../api/client'
import { useLiveSocket } from '../hooks/useLiveSocket'
import { fmtDateTime } from './ui'

export function NotificationBell() {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState({ items: [], unread: 0 })
  const ref = useRef(null)

  const load = useCallback(() => {
    api.get('/notifications', { limit: 25 }).then(setData).catch(() => {})
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [load])

  // real-time: refresh when the server pushes a notification
  useLiveSocket({ onMessage: (msg) => msg.type === 'notification' && load() })

  useEffect(() => {
    if (!open) return undefined
    const onDoc = (e) => !ref.current?.contains(e.target) && setOpen(false)
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const markAll = async () => {
    await api.post('/notifications/read').catch(() => {})
    load()
  }

  return (
    <div className="relative" ref={ref}>
      <button
        className="relative rounded-xl p-2 text-muted hover:bg-panel2 hover:text-fg"
        onClick={() => setOpen((o) => !o)}
        aria-label={`Notifications${data.unread ? `, ${data.unread} unread` : ''}`}
        aria-expanded={open}
      >
        <Bell size={19} />
        {data.unread > 0 && (
          <span className="tnum absolute -right-0.5 -top-0.5 min-w-[18px] rounded-full bg-absent px-1 text-center text-[11px] font-bold leading-[18px] text-white">
            {data.unread > 99 ? '99+' : data.unread}
          </span>
        )}
      </button>
      {open && (
        <div className="glass absolute right-0 z-30 mt-2 w-[min(92vw,380px)] animate-fade-up overflow-hidden rounded-2xl border border-line/70 shadow-2xl">
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <p className="font-bold">Notifications</p>
            {data.unread > 0 && (
              <button className="text-xs font-bold text-ink hover:underline" onClick={markAll}>
                Mark all read
              </button>
            )}
          </div>
          <ul className="max-h-[60vh] overflow-y-auto">
            {data.items.length === 0 && <li className="px-4 py-6 text-sm text-muted">Nothing new.</li>}
            {data.items.map((n) => (
              <li key={n.id} className={`border-b border-line/60 px-4 py-3 last:border-0 ${n.read ? '' : 'bg-ink/5'}`}>
                <p className="text-sm font-bold">{n.title}</p>
                <p className="text-sm text-muted">{n.message}</p>
                <p className="mt-1 text-xs text-muted">{fmtDateTime(n.created_at)}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
