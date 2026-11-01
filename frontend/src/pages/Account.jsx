import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { ErrorNote, Field, PageHeader } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'

export default function Account() {
  const { user, refresh } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [form, setForm] = useState({ current: '', next: '', repeat: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    if (form.next !== form.repeat) return setError('The new passwords do not match.')
    setBusy(true)
    try {
      await api.post('/auth/change-password', { current_password: form.current, new_password: form.next })
      await refresh()
      toast.success('Password changed')
      navigate(user?.role === 'STUDENT' ? '/me' : '/')
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title="Change password"
        description={user?.must_change_password ? 'You signed in with a one-time password. Choose your own before continuing.' : undefined}
      />
      <form onSubmit={submit} className="sheet max-w-md space-y-4 p-5">
        <Field label="Current password">{(id) => <input id={id} type="password" autoComplete="current-password" className="input" required value={form.current} onChange={set('current')} />}</Field>
        <Field label="New password" hint="At least 8 characters with a letter and a digit">
          {(id) => <input id={id} type="password" autoComplete="new-password" className="input" required minLength={8} maxLength={72} value={form.next} onChange={set('next')} />}
        </Field>
        <Field label="Repeat new password">{(id) => <input id={id} type="password" autoComplete="new-password" className="input" required value={form.repeat} onChange={set('repeat')} />}</Field>
        <ErrorNote error={error} />
        <button className="btn btn-primary" disabled={busy}>
          {busy ? 'Saving…' : 'Change password'}
        </button>
      </form>
    </>
  )
}
