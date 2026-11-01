import { useState } from 'react'
import { Check, ImageUp, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import { CameraView } from './CameraView'
import { Chip } from './ui'

export const SHOTS = [
  'Look straight at the camera',
  'Turn your head slightly to your left',
  'Turn your head slightly to your right',
  'Lift your chin a little',
  'Lower your chin a little',
  'With glasses on (skip if you never wear them)',
  'Without glasses',
  'A natural smile',
]

/**
 * Guided multi-shot capture. Every shot is checked by the server
 * (checkPath, staff: /students/quality-check) so problems are fixed before submitting.
 */
export function PhotoCapture({ cam, photos, setPhotos, max = 10, prn, checkPath = '/students/quality-check' }) {
  const [checking, setChecking] = useState(false)
  const nextPrompt = SHOTS[photos.length] || 'Any extra angle'

  const check = async (blob, mirrored = false) => {
    const preview = URL.createObjectURL(blob)
    const id = `${Date.now()}-${Math.random()}`
    setPhotos((list) => [...list, { id, blob, preview, mirrored, prompt: nextPrompt, result: null }])
    setChecking(true)
    try {
      const form = new FormData()
      form.append('photo', blob, 'shot.jpg')
      if (prn) form.append('prn', prn)
      const result = await api.form(checkPath, form)
      setPhotos((list) => list.map((p) => (p.id === id ? { ...p, result } : p)))
    } catch (err) {
      setPhotos((list) => list.map((p) => (p.id === id ? { ...p, result: { accepted: false, messages: [err.message] } } : p)))
    } finally {
      setChecking(false)
    }
  }

  const shoot = async () => {
    const blob = await cam.capture(0.92)
    if (blob) check(blob, true)
  }

  const upload = (files) => [...files].slice(0, max - photos.length).forEach((f) => check(f))
  const remove = (id) => setPhotos((list) => list.filter((p) => p.id !== id))

  return (
    <div className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
      <div>
        <CameraView cam={cam} />
        <p className="mt-3 text-lg font-bold" aria-live="polite">
          {photos.length < max ? nextPrompt : 'That is enough photos'}
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          <button className="btn btn-primary" disabled={cam.status !== 'ready' || photos.length >= max} onClick={shoot}>
            Take photo {photos.length + 1}
          </button>
          <label className="btn btn-quiet cursor-pointer">
            <ImageUp size={16} /> Upload instead
            <input type="file" accept="image/*" multiple className="sr-only" onChange={(e) => upload(e.target.files)} />
          </label>
        </div>
      </div>
      <div>
        <p className="mb-2 text-sm text-muted">
          {photos.filter((p) => p.result?.accepted).length} of {photos.length} photos usable. Remove any marked with a
          problem and retake it.
        </p>
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {photos.map((p) => (
            <li key={p.id} className={`overflow-hidden rounded-2xl border ${p.result?.accepted ? 'border-ink/60' : p.result ? 'border-absent/60' : 'border-line'}`}>
              <div className="relative">
                <img src={p.preview} alt={p.prompt} className={`aspect-square w-full object-cover ${p.mirrored ? '-scale-x-100' : ''}`} />
                <button
                  className="absolute right-1.5 top-1.5 rounded bg-black/60 p-1 text-white hover:bg-black/80"
                  onClick={() => remove(p.id)}
                  aria-label="Remove photo"
                >
                  <Trash2 size={14} />
                </button>
              </div>
              <div className="space-y-1 px-2 py-1.5 text-xs">
                {!p.result ? (
                  <span className="text-muted">{checking ? 'Checking…' : 'Waiting'}</span>
                ) : p.result.accepted ? (
                  <span className="flex items-center gap-1 font-bold text-ink">
                    <Check size={13} /> Good{p.result.pose ? `, ${p.result.pose}` : ''}
                  </span>
                ) : (
                  <span className="block text-absent">{(p.result.messages || []).join('. ')}</span>
                )}
                {p.result?.duplicate_of && (
                  <Chip tone="absent">{p.result.duplicate_of.prn ? `Matches ${p.result.duplicate_of.prn}` : 'Face already registered'}</Chip>
                )}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
