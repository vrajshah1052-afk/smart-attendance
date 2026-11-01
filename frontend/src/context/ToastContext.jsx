import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { CheckCircle2, AlertTriangle, Info, X } from 'lucide-react'

const ToastContext = createContext(null)
let nextId = 1

const ICONS = { success: CheckCircle2, error: AlertTriangle, info: Info }
const TONES = { success: 'border-ink/50', error: 'border-absent/60', info: 'border-line' }

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const dismiss = useCallback((id) => setToasts((list) => list.filter((t) => t.id !== id)), [])

  const push = useCallback(
    (kind, message, timeout = 5000) => {
      const id = nextId++
      setToasts((list) => [...list.slice(-3), { id, kind, message }])
      if (timeout) setTimeout(() => dismiss(id), timeout)
    },
    [dismiss],
  )

  const value = useMemo(
    () => ({
      success: (m) => push('success', m),
      error: (m) => push('error', typeof m === 'string' ? m : m?.message || 'Something went wrong', 8000),
      info: (m) => push('info', m),
    }),
    [push],
  )

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4 sm:items-end sm:pr-6" aria-live="polite">
        {toasts.map((t) => {
          const Icon = ICONS[t.kind]
          return (
            <div key={t.id} role="status" className={`pointer-events-auto flex w-full max-w-md items-start gap-3 rounded-2xl border bg-panel px-4 py-3 text-sm shadow-lg ${TONES[t.kind]}`}>
              <Icon size={18} className={t.kind === 'error' ? 'mt-0.5 shrink-0 text-absent' : 'mt-0.5 shrink-0 text-ink'} />
              <p className="flex-1">{t.message}</p>
              <button className="text-muted hover:text-fg" onClick={() => dismiss(t.id)} aria-label="Dismiss">
                <X size={16} />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}
