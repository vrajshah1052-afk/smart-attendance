import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { ErrorNote, Mark, PageHeader } from '../components/ui'

export default function QrMark() {
  const params = useParams()
  const [sessionId, setSessionId] = useState(params.sessionId || '')
  const [code, setCode] = useState(params.code || '')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const autoSent = useRef(false)

  const submit = async (e) => {
    e?.preventDefault()
    setBusy(true)
    setError(null)
    try {
      setResult(await api.post('/attendance/qr', { session_id: Number(sessionId), code: code.trim() }))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  // opened from a scanned QR link: submit straight away (once)
  useEffect(() => {
    if (params.sessionId && params.code && !autoSent.current) {
      autoSent.current = true
      submit()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <>
      <PageHeader
        title="Mark with attendance code"
        description="Use this only if the camera could not recognise you. Your teacher shows a code that changes every 30 seconds."
      />
      {result ? (
        <div className="sheet flex max-w-md items-center gap-4 p-5">
          <Mark status={result.status} size={52} animate />
          <div>
            <p className="font-bold">
              {result.course_code}: marked {String(result.status).toLowerCase()}
              {result.late_minutes ? ` (${result.late_minutes} min late)` : ''}
            </p>
            <Link to="/me" className="text-sm text-ink hover:underline">
              See my attendance
            </Link>
          </div>
        </div>
      ) : (
        <form onSubmit={submit} className="sheet max-w-md space-y-4 p-5">
          <div className="grid grid-cols-[1fr_1.4fr] gap-3">
            <div>
              <label className="label" htmlFor="qr-session">
                Session
              </label>
              <input id="qr-session" type="number" className="input" required value={sessionId} onChange={(e) => setSessionId(e.target.value)} />
            </div>
            <div>
              <label className="label" htmlFor="qr-code">
                Six-digit code
              </label>
              <input
                id="qr-code"
                className="input tnum tracking-[0.3em]"
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                required
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              />
            </div>
          </div>
          <ErrorNote error={error} />
          <button className="btn btn-primary w-full" disabled={busy}>
            {busy ? 'Marking…' : 'Mark me present'}
          </button>
        </form>
      )}
    </>
  )
}
