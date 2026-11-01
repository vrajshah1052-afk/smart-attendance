import { useState } from 'react'
import { api, downloadFile, saveBlob } from '../api/client'
import { Chip, ErrorNote, PageHeader } from '../components/ui'
import { useToast } from '../context/ToastContext'

export default function BulkImport() {
  const toast = useToast()
  const [file, setFile] = useState(null)
  const [atomic, setAtomic] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const upload = async (e) => {
    e.preventDefault()
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await api.form('/students/import', form, { atomic })
      setResult(res)
      toast.success(`${res.imported} imported, ${res.failed} with problems`)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const saveCredentials = () => {
    const bytes = Uint8Array.from(atob(result.credentials_csv), (c) => c.charCodeAt(0))
    saveBlob(new Blob([bytes], { type: 'text/csv' }), 'student_passwords.csv')
  }

  return (
    <>
      <PageHeader
        title="Import students from CSV"
        description="Creates profiles and portal accounts in one go. Faces are enrolled afterwards from the Students page."
        actions={
          <button className="btn btn-quiet" onClick={() => downloadFile('/students/import/template', {}, 'students_template.csv')}>
            Download template
          </button>
        }
      />
      <form onSubmit={upload} className="sheet max-w-2xl p-5">
        <p className="text-sm text-muted">
          Columns: prn, name, email, phone, branch, year, division, roll_no, consent. Consent must be yes for every row.
        </p>
        <input type="file" accept=".csv,text/csv" className="input mt-4" onChange={(e) => setFile(e.target.files?.[0] || null)} required />
        <label className="mt-4 flex items-start gap-3 text-sm">
          <input type="checkbox" checked={atomic} onChange={(e) => setAtomic(e.target.checked)} className="mt-1 h-4 w-4 accent-[rgb(var(--ink))]" />
          <span>
            <span className="font-bold">All or nothing.</span> Import nothing if any row has a problem (one database
            transaction). Otherwise valid rows are imported and the rest are reported.
          </span>
        </label>
        <ErrorNote error={error} className="mt-4" />
        <button className="btn btn-primary mt-4" disabled={busy || !file}>
          {busy ? 'Importing…' : 'Import students'}
        </button>
      </form>

      {result && (
        <section className="mt-8">
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <h2 className="text-lg">
              {result.imported} imported, {result.failed} with problems
            </h2>
            {result.credentials_csv && (
              <button className="btn btn-primary btn-sm" onClick={saveCredentials}>
                Download one-time passwords
              </button>
            )}
          </div>
          <p className="mb-3 max-w-prose text-sm text-muted">{result.message}</p>
          <div className="sheet overflow-x-auto">
            <table className="register">
              <thead>
                <tr>
                  <th className="roll">Line</th>
                  <th>PRN</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {result.rows.map((r) => (
                  <tr key={`${r.line}-${r.prn}`}>
                    <td className="roll">{r.line}</td>
                    <td>{r.prn || '–'}</td>
                    <td>{r.status === 'IMPORTED' ? <Chip tone="ink">Imported, {r.courses} courses</Chip> : <span className="text-absent">{r.error}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}
