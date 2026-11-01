import { useState } from 'react'
import { api } from '../api/client'
import { CameraView } from '../components/CameraView'
import { SessionPicker } from '../components/SessionPicker'
import { ErrorNote, Mark, PageHeader } from '../components/ui'
import { useWebcam } from '../hooks/useWebcam'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

export default function LateEntry() {
  const cam = useWebcam({ width: 1280, height: 720 })
  const [session, setSession] = useState(null)
  const [phase, setPhase] = useState('idle') // idle | countdown | recording | checking | done
  const [challenge, setChallenge] = useState(null)
  const [count, setCount] = useState(0)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const run = async () => {
    setError(null)
    setResult(null)
    try {
      const ch = await api.get('/liveness/challenge')
      setChallenge(ch)
      setPhase('countdown')
      for (let i = 3; i > 0; i -= 1) {
        setCount(i)
        await sleep(800)
      }
      setPhase('recording')
      const frames = []
      for (let i = 0; i < ch.frames; i += 1) {
        const blob = await cam.capture(0.85, 960)
        if (blob) frames.push(blob)
        await sleep(ch.interval_ms)
      }
      setPhase('checking')
      const form = new FormData()
      form.append('session_id', session.session_id)
      form.append('challenge_token', ch.token)
      frames.forEach((b, i) => form.append('frames', b, `frame${i}.jpg`))
      const res = await api.form('/attendance/late', form)
      setResult(res)
      setPhase('done')
    } catch (err) {
      setError(err)
      setPhase('done')
    }
  }

  const reset = () => {
    setPhase('idle')
    setResult(null)
    setError(null)
    setChallenge(null)
  }

  const reasons = error?.details?.messages || []
  const canStart = session?.status === 'OPEN' && cam.status === 'ready' && (phase === 'idle' || phase === 'done')

  return (
    <>
      <PageHeader
        title="Late entry"
        description="One student at a time at the door. A quick blink or head turn proves it is a live person, not a photo."
      />
      <SessionPicker value={session} onChange={setSession} />
      <section className="mt-6 grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <div>
          <CameraView cam={cam}>
            {(phase === 'countdown' || phase === 'recording' || phase === 'checking') && challenge && (
              <div className="absolute inset-x-0 bottom-0 bg-black/70 px-4 py-3 text-center text-white">
                <p className="text-lg font-bold">{challenge.instructions}</p>
                <p className="text-sm text-white/80">
                  {phase === 'countdown' && `Starting in ${count}`}
                  {phase === 'recording' && 'Recording, keep going'}
                  {phase === 'checking' && 'Checking'}
                </p>
              </div>
            )}
          </CameraView>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn btn-primary" disabled={!canStart} onClick={run}>
              {phase === 'done' ? 'Check the next student' : 'Start check'}
            </button>
            {phase === 'done' && (
              <button className="btn btn-quiet" onClick={reset}>
                Clear
              </button>
            )}
          </div>
        </div>

        <aside aria-live="polite">
          {phase === 'idle' && (
            <div className="text-sm text-muted">
              <h2 className="mb-2 text-base text-fg">How it works</h2>
              <ol className="list-decimal space-y-1.5 pl-5">
                <li>Only the late student should be in front of the camera.</li>
                <li>Press Start check and follow the instruction on screen for about three seconds.</li>
                <li>The student is marked late with the minutes counted from the start of the session. Within the grace period they are marked present.</li>
              </ol>
            </div>
          )}
          {result && (
            <div className="sheet p-5">
              <div className="flex items-start gap-4">
                <Mark status={result.status} size={56} animate />
                <div>
                  <p className="text-xl font-bold">{result.name}</p>
                  <p className="text-sm text-muted">{result.prn}</p>
                  <p className="mt-2">
                    {result.status === 'LATE'
                      ? `Marked late by ${result.late_minutes} minute${result.late_minutes === 1 ? '' : 's'}.`
                      : 'Within the grace period, marked present.'}
                  </p>
                  <p className="mt-1 text-sm text-muted">
                    Similarity {result.confidence.toFixed(2)}, liveness passed ({result.liveness?.challenge === 'BLINK' ? 'blink' : 'head turn'}).
                    {result.auto_reenrolled && ' A fresh face template was saved because recent matches were weak.'}
                  </p>
                </div>
              </div>
            </div>
          )}
          {error && (
            <div>
              <ErrorNote error={error} />
              {reasons.length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
                  {reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              )}
              {error.code === 'ALREADY_MARKED' && <p className="mt-2 text-sm text-muted">This student already has a mark for this session.</p>}
              {error.code === 'UNKNOWN_FACE' && (
                <p className="mt-2 text-sm text-muted">If the student is enrolled in this course, try again closer to the camera, or use the class code.</p>
              )}
            </div>
          )}
        </aside>
      </section>
    </>
  )
}
