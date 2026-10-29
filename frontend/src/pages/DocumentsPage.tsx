import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type DragEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError, type DocType } from '../api/client'
import { formatDate, useHealth } from '../lib'
import { useLang, useT } from '../strings'

const EXTENSIONS = ['.docx', '.pdf', '.txt', '.md']
const DEFAULT_MAX_MB = 20

export default function DocumentsPage() {
  const t = useT()
  const lang = useLang()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const maxMb = useHealth().data?.max_upload_mb ?? DEFAULT_MAX_MB
  const [docType, setDocType] = useState<DocType>('report')
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [over, setOver] = useState(false)
  const docs = useQuery({ queryKey: ['documents'], queryFn: api.listDocuments })

  const upload = useMutation({
    mutationFn: (f: File) => api.uploadDocument(f, docType),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ['documents'] })
      if (d.duplicate) setNote(t.docs.duplicate)
      navigate(`/documents/${d.id}`)
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : String(e)),
  })

  const remove = useMutation({
    mutationFn: api.deleteDocument,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents'] }),
    onError: (e) => setError(e instanceof ApiError ? e.message : String(e)),
  })

  function pick(f: File | undefined) {
    setError(null)
    setNote(null)
    if (!f) return
    const ext = f.name.slice(f.name.lastIndexOf('.')).toLowerCase()
    if (!EXTENSIONS.includes(ext)) return setError(t.docs.wrongType)
    if (f.size > maxMb * 1024 * 1024) return setError(t.docs.tooLarge(maxMb))
    upload.mutate(f)
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setOver(false)
    if (!upload.isPending) pick(e.dataTransfer.files[0])
  }

  return (
    <div className="page">
      <h1 className="page-title">{t.docs.title}</h1>
      <p className="lede">{t.docs.intro}</p>

      <div
        className="tray"
        data-over={over || undefined}
        data-busy={upload.isPending || undefined}
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        {upload.isPending ? (
          <p aria-live="polite">{t.docs.uploading}</p>
        ) : (
          <p>
            {t.docs.drop}{' '}
            <label className="link-like">
              {t.docs.choose}
              <input
                type="file"
                className="sr-only"
                accept={EXTENSIONS.join(',')}
                disabled={upload.isPending}
                onChange={(e) => {
                  pick(e.target.files?.[0])
                  e.target.value = ''
                }}
              />
            </label>
          </p>
        )}
        <label className="mt-3 flex items-center gap-2 text-[13px] text-graphite">
          {t.docs.typeLabel}
          <select
            className="field py-1 text-ink"
            value={docType}
            onChange={(e) => setDocType(e.target.value as DocType)}
          >
            {(Object.keys(t.docType) as DocType[]).map((k) => (
              <option key={k} value={k}>
                {t.docType[k]}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && (
        <p role="alert" className="alert mt-3">
          {error}
        </p>
      )}
      {note && <p className="mt-3 text-graphite">{note}</p>}

      {docs.data?.length === 0 && <p className="mt-8 text-graphite">{t.docs.empty}</p>}
      {docs.error && <p className="alert mt-6">{(docs.error as Error).message}</p>}
      {!!docs.data?.length && (
        <table className="ledger mt-8">
          <thead>
            <tr>
              <th>{t.docs.cols.file}</th>
              <th>{t.docs.cols.type}</th>
              <th className="num">{t.docs.cols.sections}</th>
              <th className="num">{t.docs.cols.figures}</th>
              <th>{t.docs.cols.review}</th>
              <th>{t.docs.cols.uploaded}</th>
              <th>
                <span className="sr-only">{t.docs.delete}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {docs.data.map((d) => (
              <tr key={d.id}>
                <td>
                  <Link to={`/documents/${d.id}`} className="file-link">
                    {d.filename}
                  </Link>
                </td>
                <td>{t.docType[d.doc_type]}</td>
                <td className="num">{d.section_count}</td>
                <td className="num">{d.figure_count}</td>
                <td>
                  {d.latest_review ? (
                    <span className="flex items-baseline gap-2">
                      <span className={`status-dot status-${d.latest_review.status}`} aria-hidden />
                      {t.status[d.latest_review.status]}
                    </span>
                  ) : (
                    <span className="text-graphite">{t.docs.notReviewed}</span>
                  )}
                </td>
                <td className="text-graphite">{formatDate(d.created_at, lang)}</td>
                <td className="text-right">
                  <button
                    className="btn-quiet"
                    aria-label={`${t.docs.delete} ${d.filename}`}
                    onClick={() =>
                      window.confirm(t.docs.confirmDelete(d.filename)) && remove.mutate(d.id)
                    }
                  >
                    {t.docs.delete}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
