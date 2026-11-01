import { useState } from 'react'
import { api } from '../api/client'
import { Empty, ErrorNote, PageHeader, Spinner, Tabs, fmtDateTime } from '../components/ui'
import { useToast } from '../context/ToastContext'
import { useApi } from '../hooks/useApi'
import { useAuthedImage } from '../hooks/useAuthedImage'

function ReviewItem({ item, onDone }) {
  const toast = useToast()
  const image = useAuthedImage(item.snapshot_id ? `/snapshots/${item.snapshot_id}` : null)
  const options = [{ prn: item.prn, name: item.name, score: item.confidence }, ...(item.suggestions || []).filter((s) => s.prn !== item.prn)]
  const [prn, setPrn] = useState(item.prn || '')
  const [learn, setLearn] = useState(false)
  const [busy, setBusy] = useState(false)
  const pending = item.status === 'PENDING'

  const decide = async (approve) => {
    setBusy(true)
    try {
      const res = await api.post(`/review/${item.id}/${approve ? 'approve' : 'reject'}`, { prn: prn || null, add_to_profile: learn })
      toast.success(approve ? `Marked ${res.prn} present${res.template_added ? ' and saved the face' : ''}` : 'Match rejected')
      onDone()
    } catch (err) {
      toast.error(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="flex flex-col gap-4 border-b border-line px-4 py-4 last:border-0 sm:flex-row">
      {image ? (
        <img src={image} alt="Face to review" className="h-28 w-28 shrink-0 rounded object-cover" />
      ) : (
        <div className="flex h-28 w-28 shrink-0 items-center justify-center rounded bg-panel2 text-center text-xs text-muted">Photo expired</div>
      )}
      <div className="min-w-0 flex-1">
        <p className="font-bold">
          Is this {item.name || item.prn}?
        </p>
        <p className="text-sm text-muted">
          Session {item.session_id}, similarity {Number(item.confidence).toFixed(2)}, from a {String(item.source || '').toLowerCase()} capture,{' '}
          {fmtDateTime(item.created_at)}
        </p>
        {pending ? (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <select className="input w-auto" value={prn} onChange={(e) => setPrn(e.target.value)} aria-label="Student">
              {options.map((o) => (
                <option key={o.prn} value={o.prn}>
                  {o.name || o.prn} ({Number(o.score).toFixed(2)})
                </option>
              ))}
            </select>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={learn} onChange={(e) => setLearn(e.target.checked)} className="h-4 w-4 accent-[rgb(var(--ink))]" />
              Save this face to their profile
            </label>
            <span className="flex-1" />
            <button className="btn btn-quiet btn-sm" disabled={busy} onClick={() => decide(false)}>
              Not them
            </button>
            <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => decide(true)}>
              Yes, mark present
            </button>
          </div>
        ) : (
          <p className="mt-2 text-sm">{item.status === 'APPROVED' ? `Approved for ${item.result?.prn}` : 'Rejected'}</p>
        )}
      </div>
    </li>
  )
}

export default function ReviewQueue() {
  const [status, setStatus] = useState('PENDING')
  const items = useApi(() => api.get('/review', { status }), [status])
  return (
    <>
      <PageHeader
        title="Review matches"
        description="Faces the system was unsure about. Confirm or reject them; a confirmed face can also be saved to improve future recognition."
      />
      <Tabs
        value={status}
        onChange={setStatus}
        tabs={[
          { value: 'PENDING', label: 'Waiting' },
          { value: 'APPROVED', label: 'Approved' },
          { value: 'REJECTED', label: 'Rejected' },
        ]}
      />
      <ErrorNote error={items.error} />
      <ul className="sheet">
        {items.loading ? (
          <Spinner className="p-4" />
        ) : !items.data?.length ? (
          <Empty title={status === 'PENDING' ? 'Nothing to review' : 'No items'}>Uncertain matches from group photos and late entries appear here.</Empty>
        ) : (
          items.data.map((it) => <ReviewItem key={it.id} item={it} onDone={items.reload} />)
        )}
      </ul>
    </>
  )
}
