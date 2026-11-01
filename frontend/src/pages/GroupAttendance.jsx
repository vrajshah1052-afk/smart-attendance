import { useEffect, useMemo, useState } from 'react'
import { Camera, ImageUp, RotateCcw } from 'lucide-react'
import { api } from '../api/client'
import { CameraView } from '../components/CameraView'
import { SessionPicker } from '../components/SessionPicker'
import { Chip, ErrorNote, Mark, PageHeader, Spinner, Tabs } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { useWebcam } from '../hooks/useWebcam'

const STATUS = {
  MATCHED: { tone: 'ink', text: 'Recognised' },
  LOW_CONFIDENCE: { tone: 'late', text: 'Recognised, low confidence' },
  POSSIBLE: { tone: 'late', text: 'Possible match' },
  UNKNOWN: { tone: 'absent', text: 'Unknown' },
  TOO_SMALL: { tone: 'muted', text: 'Too small to identify' },
  SPOOF_SUSPECTED: { tone: 'spoof', text: 'Looks like a photo or screen' },
}

function FaceItem({ face, picked, onToggle }) {
  const s = STATUS[face.status] || STATUS.UNKNOWN
  const tickable = face.prn && face.status !== 'UNKNOWN'
  return (
    <li className="flex items-center gap-3 border-b border-line/70 px-3 py-2.5 last:border-0">
      {face.crop ? (
        <img src={face.crop} alt={`Face ${face.face_index + 1}`} className="h-12 w-12 shrink-0 rounded object-cover" />
      ) : (
        <div className="h-12 w-12 shrink-0 rounded bg-panel2" />
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-bold">
          #{face.face_index + 1} {face.name || (face.status === 'UNKNOWN' ? 'Not in this class' : '')}
        </p>
        <div className="mt-0.5 flex flex-wrap items-center gap-2">
          <Chip tone={s.tone}>{s.text}</Chip>
          {face.confidence != null && <span className="tnum text-xs text-muted">similarity {face.confidence.toFixed(2)}</span>}
        </div>
        {face.status === 'UNKNOWN' && face.suggestions?.length > 0 && (
          <p className="mt-1 text-xs text-muted">Closest: {face.suggestions.map((x) => x.name || x.prn).join(', ')}</p>
        )}
      </div>
      {tickable && (
        <label className="flex cursor-pointer items-center gap-2 text-sm">
          <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--ink))]" checked={picked} onChange={onToggle} />
          Present
        </label>
      )}
    </li>
  )
}

export default function GroupAttendance() {
  const toast = useToast()
  const cam = useWebcam({ width: 1920, height: 1080, facingMode: 'environment' })
  const [session, setSession] = useState(null)
  const [source, setSource] = useState('camera')
  const [config, setConfig] = useState(null)
  const [threshold, setThreshold] = useState(null)
  const [analysis, setAnalysis] = useState(null)
  const [picked, setPicked] = useState(new Set())
  const [manual, setManual] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(null)

  useEffect(() => {
    api.get('/config/public').then((c) => {
      setConfig(c)
      setThreshold(c.match_threshold)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    setAnalysis(null)
    setSaved(null)
    setError(null)
  }, [session?.session_id])

  const analyse = async (blob) => {
    if (!session) return toast.error('Choose a session first')
    setBusy(true)
    setError(null)
    setSaved(null)
    try {
      const form = new FormData()
      form.append('session_id', session.session_id)
      form.append('photo', blob, 'class.jpg')
      if (threshold) form.append('threshold', threshold)
      const res = await api.form('/attendance/group', form)
      setAnalysis(res)
      setPicked(new Set(res.faces.filter((f) => f.prn && ['MATCHED', 'LOW_CONFIDENCE'].includes(f.status)).map((f) => f.prn)))
      setManual({})
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const captureFromCamera = async () => {
    const blob = await cam.capture(0.92)
    if (!blob) return toast.error('The camera is not ready yet')
    analyse(blob)
  }

  const togglePick = (prn) =>
    setPicked((prev) => {
      const next = new Set(prev)
      next.has(prn) ? next.delete(prn) : next.add(prn)
      return next
    })

  const recognisable = useMemo(() => new Set((analysis?.faces || []).filter((f) => f.prn).map((f) => f.prn)), [analysis])

  const toggleRosterRow = (row) => {
    if (row.already_marked) return
    if (recognisable.has(row.prn)) return togglePick(row.prn)
    setManual((m) => {
      const next = { ...m }
      if (row.prn in next) delete next[row.prn]
      else next[row.prn] = ''
      return next
    })
  }

  const manualList = Object.entries(manual)
  const missingReason = manualList.some(([, r]) => r.trim().length < 5)
  const toMark = picked.size + manualList.length

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await api.post('/attendance/group/confirm', {
        draft_id: analysis.draft_id,
        session_id: session.session_id,
        prns: [...picked],
        manual: manualList.map(([prn, reason]) => ({ prn, reason: reason.trim() })),
      })
      setSaved(res)
      toast.success(`Saved: ${res.inserted} student${res.inserted === 1 ? '' : 's'} marked present`)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const closeSession = async () => {
    if (!window.confirm('Close the session? Everyone not marked yet becomes absent.')) return
    try {
      const res = await api.post(`/sessions/${session.session_id}/close`)
      toast.success(`Session closed. ${res.absent_marked} marked absent.`)
      setSession({ ...session, status: 'CLOSED' })
    } catch (err) {
      toast.error(err)
    }
  }

  const savedSet = new Set(saved?.marked_prns || [])
  const multiDivision = new Set((analysis?.roster || []).map((r) => r.division)).size > 1
  const faces = analysis?.faces || []

  return (
    <>
      <PageHeader
        title="Take attendance"
        description="Photograph the whole class, check the names, then save. Nothing is recorded until you save."
      />
      <SessionPicker value={session} onChange={setSession} />

      {session?.status === 'OPEN' && !analysis && (
        <section className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
          <div>
            <Tabs
              value={source}
              onChange={setSource}
              tabs={[
                { value: 'camera', label: 'Use camera' },
                { value: 'upload', label: 'Upload a photo' },
              ]}
            />
            {source === 'camera' ? (
              <>
                <CameraView cam={cam} guide="none" />
                <button className="btn btn-primary mt-3 w-full sm:w-auto" disabled={busy || cam.status !== 'ready'} onClick={captureFromCamera}>
                  <Camera size={16} /> {busy ? 'Recognising faces…' : 'Capture class photo'}
                </button>
              </>
            ) : (
              <label className="sheet flex cursor-pointer flex-col items-center justify-center gap-2 px-6 py-14 text-center hover:bg-panel2">
                <ImageUp size={26} className="text-muted" />
                <span className="font-bold">Choose a class photo</span>
                <span className="text-sm text-muted">JPEG or PNG, up to {config ? config.max_upload_mb * 2 : 16} MB</span>
                <input
                  type="file"
                  accept="image/*"
                  className="sr-only"
                  onChange={(e) => e.target.files?.[0] && analyse(e.target.files[0])}
                />
              </label>
            )}
            {busy && <Spinner label="Detecting and matching faces" className="mt-3" />}
            <ErrorNote error={error} className="mt-3" />
          </div>
          <aside className="text-sm text-muted">
            <h2 className="mb-2 text-base text-fg">For a good group photo</h2>
            <ul className="list-disc space-y-1.5 pl-5">
              <li>Stand at the front so every face is visible and roughly the size of a thumbnail or larger.</li>
              <li>Ask students to look up; turn on the classroom lights and avoid shooting into windows.</li>
              <li>Large classes: take two photos (left and right half). Each photo only adds students.</li>
            </ul>
            {threshold != null && (
              <details className="mt-5">
                <summary className="cursor-pointer font-bold text-fg">Matching strictness</summary>
                <label className="mt-3 block" htmlFor="thr">
                  Similarity needed to recognise someone: <span className="tnum font-bold text-fg">{Number(threshold).toFixed(2)}</span>
                </label>
                <input id="thr" type="range" min="0.3" max="0.7" step="0.01" value={threshold} onChange={(e) => setThreshold(e.target.value)} className="w-full accent-[rgb(var(--ink))]" />
                <p className="hint">Higher is stricter: fewer wrong matches, more unknown faces.</p>
              </details>
            )}
          </aside>
        </section>
      )}

      {analysis && (
        <section className="mt-6 grid gap-6 xl:grid-cols-[1.35fr_1fr]">
          <div className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <h2 className="text-lg">
                {analysis.summary.detected} face{analysis.summary.detected === 1 ? '' : 's'} found
              </h2>
              <span className="text-sm text-muted">in {Math.round(analysis.latency_ms)} ms</span>
              <span className="flex-1" />
              <button className="btn btn-quiet btn-sm" onClick={() => setAnalysis(null)}>
                <RotateCcw size={14} /> Take another photo
              </button>
            </div>
            <img src={analysis.annotated_image} alt="Class photo with recognised faces outlined" className="w-full rounded-2xl border border-line" />
            <ul className="sheet mt-4">
              {faces.map((f) => (
                <FaceItem key={f.face_index} face={f} picked={picked.has(f.prn)} onToggle={() => togglePick(f.prn)} />
              ))}
            </ul>
          </div>

          <div className="min-w-0">
            <h2 className="mb-1 text-lg">Register</h2>
            <p className="mb-3 text-sm text-muted">
              Tick anyone you can see in class who was missed; you will be asked why. Unknown faces stay unmarked.
            </p>
            <div className="sheet max-h-[70vh] overflow-y-auto">
              <table className="register">
                <thead className="sticky top-0 bg-panel">
                  <tr>
                    <th className="roll">Roll</th>
                    <th>Student</th>
                    <th className="w-16 text-center">Mark</th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.roster.map((row, i) => {
                    const isPicked = picked.has(row.prn)
                    const isManual = row.prn in manual
                    const status = row.already_marked || (savedSet.has(row.prn) || isPicked || isManual ? 'PRESENT' : null)
                    return (
                      <tr key={row.prn} className={row.already_marked ? '' : 'cursor-pointer'} onClick={() => toggleRosterRow(row)}>
                        <td className="roll">{multiDivision ? `${row.division}-${row.roll_no}` : row.roll_no}</td>
                        <td>
                          <span className={row.already_marked ? 'text-muted' : ''}>{row.full_name}</span>
                          {row.face_status === 'PENDING' && <span className="ml-2 text-xs text-late">no face enrolled</span>}
                          {row.suggested && !isPicked && <span className="ml-2 text-xs text-late">possible match</span>}
                          {isManual && (
                            <input
                              className="input mt-1.5"
                              placeholder="Why are you adding this student? (min 5 characters)"
                              value={manual[row.prn]}
                              onClick={(e) => e.stopPropagation()}
                              onChange={(e) => setManual((m) => ({ ...m, [row.prn]: e.target.value }))}
                              autoFocus
                            />
                          )}
                        </td>
                        <td className="text-center">
                          <span className={!row.already_marked && !saved && status ? 'opacity-60' : ''}>
                            <Mark status={status} animate={savedSet.has(row.prn)} delay={i * 35} />
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <ErrorNote error={error} className="mt-3" />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {!saved ? (
                <>
                  <p className="flex-1 text-sm text-muted">
                    {toMark} student{toMark === 1 ? '' : 's'} will be marked present.
                  </p>
                  <button className="btn btn-primary" disabled={busy || toMark === 0 || missingReason} onClick={save}>
                    {busy ? 'Saving…' : 'Save attendance'}
                  </button>
                </>
              ) : (
                <>
                  <p className="flex-1 text-sm">
                    Saved {saved.inserted} new mark{saved.inserted === 1 ? '' : 's'}
                    {saved.duplicates.length > 0 && `, ${saved.duplicates.length} were already marked`}.
                  </p>
                  <button className="btn btn-quiet" onClick={() => setAnalysis(null)}>
                    Take another photo
                  </button>
                  {session?.status === 'OPEN' && (
                    <button className="btn btn-danger" onClick={closeSession}>
                      Close session
                    </button>
                  )}
                </>
              )}
            </div>
            {missingReason && <p className="mt-2 text-xs text-late">Add a reason for every student you ticked by hand.</p>}
          </div>
        </section>
      )}
    </>
  )
}
