import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError, type KBCategory, type KBHit } from '../api/client'
import { useLang, useT } from '../strings'
import { formatDate, useHealth } from '../lib'

const APPLIES_TO = ['any', 'report', 'proposal', 'technical'] as const

export default function KnowledgeBasePage() {
  const t = useT()
  const lang = useLang()
  const qc = useQueryClient()
  const health = useHealth().data
  const [category, setCategory] = useState<KBCategory>('standard')
  const [appliesTo, setAppliesTo] = useState<string>('any')
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<KBHit[] | null>(null)
  const enabled = health?.kb_configured !== false
  const sources = useQuery({ queryKey: ['kb'], queryFn: api.listSources, enabled })

  const fail = (e: unknown) =>
    setError(
      e instanceof ApiError
        ? e.code === 'DUPLICATE_SOURCE'
          ? t.kb.duplicate
          : e.message
        : String(e),
    )
  const done = () => qc.invalidateQueries({ queryKey: ['kb'] })
  const add = useMutation({
    mutationFn: (f: File) => api.addSource(f, category, appliesTo),
    onSuccess: done,
    onError: fail,
  })
  const remove = useMutation({ mutationFn: api.deleteSource, onSuccess: done, onError: fail })
  const reindex = useMutation({
    mutationFn: api.reindexKB,
    onSuccess: () => {
      done()
      qc.invalidateQueries({ queryKey: ['health'] })
    },
    onError: fail,
  })
  const search = useMutation({
    mutationFn: () => api.searchKB(query, category),
    onSuccess: setHits,
    onError: fail,
  })

  const appliesLabel = (v: string) =>
    v === 'any' ? t.kb.any : t.docType[v as keyof typeof t.docType]

  return (
    <div className="page">
      <h1 className="page-title">{t.kb.title}</h1>
      <p className="lede">{t.kb.intro}</p>
      {!enabled && (
        <p role="status" className="banner-inline mt-4">
          {t.kb.notConfigured}
        </p>
      )}
      {health?.kb_needs_reindex && (
        <p role="status" className="banner-inline mt-4">
          {t.kb.reindexNeeded}{' '}
          <button
            className="btn btn-ink ml-2"
            disabled={reindex.isPending}
            onClick={() => reindex.mutate()}
          >
            {t.kb.reindex}
          </button>
        </p>
      )}

      {enabled && (
        <>
          <div className="mt-6 flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-0.5 text-[13px] text-graphite">
              {t.kb.cols.category}
              <select
                className="field py-1 text-ink"
                value={category}
                onChange={(e) => setCategory(e.target.value as KBCategory)}
              >
                {(Object.keys(t.kb.category) as KBCategory[]).map((k) => (
                  <option key={k} value={k}>
                    {t.kb.category[k]}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-0.5 text-[13px] text-graphite">
              {t.kb.appliesTo}
              <select
                className="field py-1 text-ink"
                value={appliesTo}
                onChange={(e) => setAppliesTo(e.target.value)}
              >
                {APPLIES_TO.map((k) => (
                  <option key={k} value={k}>
                    {appliesLabel(k)}
                  </option>
                ))}
              </select>
            </label>
            <label className={`btn btn-ink ${add.isPending ? 'opacity-60' : ''}`}>
              {add.isPending ? t.kb.adding : t.kb.add}
              <input
                type="file"
                className="sr-only"
                accept=".docx,.pdf,.txt,.md"
                disabled={add.isPending}
                onChange={(e) => {
                  setError(null)
                  const f = e.target.files?.[0]
                  if (f) add.mutate(f)
                  e.target.value = ''
                }}
              />
            </label>
          </div>
          {error && (
            <p role="alert" className="alert mt-3">
              {error}
            </p>
          )}

          {sources.data?.length === 0 && <p className="mt-6 text-graphite">{t.kb.empty}</p>}
          {!!sources.data?.length && (
            <table className="ledger mt-6">
              <thead>
                <tr>
                  <th>{t.kb.cols.file}</th>
                  <th>{t.kb.cols.category}</th>
                  <th>{t.kb.cols.appliesTo}</th>
                  <th className="num">{t.kb.cols.chunks}</th>
                  <th>{t.kb.cols.added}</th>
                  <th>
                    <span className="sr-only">{t.kb.delete}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {sources.data.map((s) => (
                  <tr key={s.id}>
                    <td>{s.filename}</td>
                    <td>{t.kb.category[s.category]}</td>
                    <td>{appliesLabel(s.doc_type)}</td>
                    <td className="num">{s.chunk_count}</td>
                    <td className="text-graphite">{formatDate(s.created_at, lang)}</td>
                    <td className="text-right">
                      <button
                        className="btn-quiet"
                        aria-label={`${t.kb.delete} ${s.filename}`}
                        onClick={() =>
                          window.confirm(t.kb.confirmDelete(s.filename)) && remove.mutate(s.id)
                        }
                      >
                        {t.kb.delete}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <section className="mt-10 max-w-2xl">
            <h2 className="section-title">{t.kb.test}</h2>
            <p className="mt-1 text-graphite">{t.kb.testHint}</p>
            <form
              className="mt-3 flex gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                if (query.trim()) search.mutate()
              }}
            >
              <input
                className="field flex-1"
                aria-label={t.kb.test}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <button className="btn btn-ink" disabled={search.isPending}>
                {t.kb.search}
              </button>
            </form>
            {hits?.length === 0 && <p className="mt-3 text-graphite">{t.kb.noHits}</p>}
            {hits && hits.length > 0 && (
              <ol className="mt-4 space-y-4">
                {hits.map((h) => (
                  <li key={h.chunk_id} className="hit">
                    <p className="text-[13px] text-graphite">
                      {h.filename}, {t.kb.distance} {h.score.toFixed(2)}
                    </p>
                    <p className="mt-1 whitespace-pre-line font-serif">{h.text}</p>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      )}
    </div>
  )
}
