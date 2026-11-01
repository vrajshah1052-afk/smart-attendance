import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { CameraView } from '../components/CameraView'
import { SessionPicker } from '../components/SessionPicker'
import { Chip, Empty, PageHeader } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { useTheme } from '../context/ThemeContext'
import { useLiveSocket } from '../hooks/useLiveSocket'
import { useWebcam } from '../hooks/useWebcam'

const EVENT_TEXT = {
  attendance_committed: (d) => `${d.course_code}: ${d.inserted} marked from a photo`,
  late_marked: (d) => `${d.name || d.prn} marked ${String(d.status).toLowerCase()}${d.late_minutes ? ` (${d.late_minutes} min)` : ''}`,
  spoof_attempt: (d) => `Spoof attempt blocked: ${(d.reasons || []).join(', ').toLowerCase()}`,
  session_opened: (d) => `${d.course_code} opened`,
  session_closed: (d) => `Session closed, ${d.absent_marked} absent`,
  qr_marked: (d) => `${d.prn} used the attendance code`,
  live_seen: (d) => `Seen: ${(d.students || []).map((s) => s.name || s.prn).join(', ')}`,
  notification: (d) => d.title,
}

export default function LiveFeed() {
  const toast = useToast()
  const { colors } = useTheme()
  const cam = useWebcam({ width: 1280, height: 720 })
  const [session, setSession] = useState(null)
  const [running, setRunning] = useState(false)
  const [latest, setLatest] = useState(null)
  const [events, setEvents] = useState([])
  const [busy, setBusy] = useState(false)
  const overlayRef = useRef(null)
  const waiting = useRef(0) // timestamp of the frame in flight (0 = none)

  const onMessage = useCallback((msg) => {
    if (msg.type === 'recognition') {
      waiting.current = 0
      setLatest(msg)
    } else if (msg.type === 'error') {
      waiting.current = 0
      if (msg.data?.code) toast.error(msg.data.detail)
    } else if (EVENT_TEXT[msg.type]) {
      setEvents((list) => [{ id: `${msg.ts}-${Math.random()}`, ts: msg.ts, type: msg.type, text: EVENT_TEXT[msg.type](msg.data || {}) }, ...list].slice(0, 40))
    }
  }, [toast])

  const { state, send } = useLiveSocket({ onMessage })

  const camRef = useRef(cam)
  camRef.current = cam

  // frame loop: one frame in flight at a time (server applies back-pressure too)
  useEffect(() => {
    if (!running || !session) return undefined
    const timer = setInterval(() => {
      const c = camRef.current
      if ((waiting.current && Date.now() - waiting.current < 5000) || c.status !== 'ready') return
      const image = c.captureDataUrl(640, 0.7)
      if (image && send({ type: 'frame', session_id: session.session_id, image })) waiting.current = Date.now()
    }, 500)
    return () => clearInterval(timer)
  }, [running, session, send])

  // draw boxes; the preview is mirrored, so mirror x when drawing
  useEffect(() => {
    const canvas = overlayRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    canvas.width = rect.width
    canvas.height = rect.height
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    if (!latest || !running) return
    const { width: fw, height: fh } = latest.frame
    // object-cover scaling
    const scale = Math.max(canvas.width / fw, canvas.height / fh)
    const offX = (canvas.width - fw * scale) / 2
    const offY = (canvas.height - fh * scale) / 2
    ctx.font = 'bold 13px "Atkinson Hyperlegible", sans-serif'
    latest.faces.forEach((f) => {
      const [x1, y1, x2, y2] = f.bbox
      const left = canvas.width - (x2 * scale + offX)
      const top = y1 * scale + offY
      const w = (x2 - x1) * scale
      const h = (y2 - y1) * scale
      const color = f.status === 'MATCHED' ? colors.ink : f.status === 'LOW_CONFIDENCE' ? colors.late : f.status === 'SPOOF_SUSPECTED' ? colors.spoof : colors.absent
      ctx.strokeStyle = color
      ctx.lineWidth = 2.5
      ctx.strokeRect(left, top, w, h)
      const label = f.name ? `${f.name} ${f.confidence?.toFixed(2) ?? ''}` : 'Unknown'
      const tw = ctx.measureText(label).width + 10
      ctx.fillStyle = color
      ctx.fillRect(left, Math.max(0, top - 20), tw, 20)
      ctx.fillStyle = '#0E1A16'
      ctx.fillText(label, left + 5, Math.max(14, top - 6))
    })
  }, [latest, running, colors])

  const commit = async () => {
    if (!latest?.draft_id || !latest.seen.length) return
    setBusy(true)
    try {
      const res = await api.post('/attendance/group/confirm', {
        draft_id: latest.draft_id,
        session_id: session.session_id,
        prns: latest.seen.map((s) => s.prn),
      })
      toast.success(`Saved: ${res.inserted} marked present, ${res.duplicates.length} already marked`)
      setLatest(null)
      setRunning(false)
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Live recognition"
        description="Point the camera at the doorway or the class. Recognised students collect on the right; save them when you are done."
        actions={<Chip tone={state === 'open' ? 'ink' : 'absent'}>{state === 'open' ? 'Connected' : state === 'connecting' ? 'Connecting' : 'Offline'}</Chip>}
      />
      <SessionPicker value={session} onChange={setSession} />
      <section className="mt-6 grid gap-6 xl:grid-cols-[1.5fr_1fr]">
        <div>
          <CameraView cam={cam} guide="none">
            <canvas ref={overlayRef} className="pointer-events-none absolute inset-0 h-full w-full" />
          </CameraView>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              className={`btn ${running ? 'btn-quiet' : 'btn-primary'}`}
              disabled={session?.status !== 'OPEN' || cam.status !== 'ready' || state !== 'open'}
              onClick={() => {
                waiting.current = 0
                setRunning((r) => !r)
              }}
            >
              {running ? 'Pause recognition' : 'Start recognition'}
            </button>
            {latest && <span className="text-sm text-muted">{Math.round(latest.latency_ms)} ms per frame</span>}
          </div>
        </div>
        <div className="flex flex-col gap-6">
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-lg">Seen in this session</h2>
              <button className="btn btn-primary btn-sm" disabled={busy || !latest?.seen?.length} onClick={commit}>
                Save {latest?.seen?.length || 0} as present
              </button>
            </div>
            <div className="sheet max-h-72 overflow-y-auto">
              {!latest?.seen?.length ? (
                <Empty title="Nobody recognised yet">Start recognition and ask students to face the camera.</Empty>
              ) : (
                <ul>
                  {latest.seen.map((s) => (
                    <li key={s.prn} className="flex items-center justify-between border-b border-line/70 px-4 py-2 text-sm last:border-0">
                      <span>
                        <span className="font-bold">{s.name}</span> <span className="text-muted">{s.prn}</span>
                      </span>
                      <span className="tnum text-muted">{s.confidence.toFixed(2)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
          <section>
            <h2 className="mb-2 text-lg">Activity</h2>
            <ul className="sheet max-h-72 overflow-y-auto text-sm">
              {events.length === 0 && <li className="px-4 py-4 text-muted">Events from every classroom appear here as they happen.</li>}
              {events.map((e) => (
                <li key={e.id} className="flex gap-3 border-b border-line/70 px-4 py-2 last:border-0">
                  <span className="tnum shrink-0 text-muted">{new Date(e.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                  <span className={e.type === 'spoof_attempt' ? 'text-spoof' : ''}>{e.text}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </section>
    </>
  )
}
