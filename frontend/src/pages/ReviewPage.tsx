import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  api,
  ApiError,
  CATEGORIES,
  SEVERITIES,
  type Category,
  type CommentStatus,
  type DocumentOut,
  type Review,
  type ReviewComment,
  type Severity,
} from '../api/client'
import CommentCard from '../components/CommentCard'
import DocumentViewer from '../components/DocumentViewer'
import IssueFilter from '../components/IssueFilter'
import { applyFilter, NO_FILTER, type Filter } from '../lib'
import SummaryPanel from '../components/SummaryPanel'
import { useT, type Strings } from '../strings'

const ACTIVE = ['queued', 'running']
const POLL_MS = 2000

function progress(stage: string): number {
  const m = stage.match(/^sections (\d+)\/(\d+)$/)
  if (m) return Math.max(15, Math.round((100 * Number(m[1])) / Math.max(1, Number(m[2]))))
  return { figures: 5, summary: 10, format: 15, done: 100 }[stage] ?? 2
}

function stageLabel(t: Strings, stage: string): string {
  const [name, count] = stage.split(' ')
  return `${t.stage[name] ?? t.status.queued}${count ? ` ${count}` : ''}`
}

function jump(elementId: string) {
  document.getElementById(elementId)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

/** Notes in document order: by section, then paragraph; whole-document notes last. */
function inDocumentOrder(doc: DocumentOut, cs: ReviewComment[]) {
  const groups = doc.sections
    .map((s) => ({
      id: s.id,
      heading: s.heading as string | null,
      notes: cs.filter((c) => c.section_id === s.id),
    }))
    .filter((g) => g.notes.length)
  const known = new Set(doc.sections.map((s) => s.id))
  const rest = cs.filter((c) => !c.section_id || !known.has(c.section_id))
  if (rest.length) groups.push({ id: 'general', heading: null, notes: rest })
  return groups
}

export default function ReviewPage() {
  const t = useT()
  const docId = Number(useParams().id)
  const qc = useQueryClient()
  const [reviewId, setReviewId] = useState<number | null>(null)
  const [activeId, setActiveId] = useState<number | null>(null)
  const [fresh, setFresh] = useState<number | null>(null)
  const [filter, setFilter] = useState<Filter>(NO_FILTER)
  const [error, setError] = useState<string | null>(null)
  const [selection, setSelection] = useState<{ pid: string; quote: string } | null>(null)
  const [draft, setDraft] = useState<{ pid: string | null; quote: string | null } | null>(null)

  const docQ = useQuery({ queryKey: ['document', docId], queryFn: () => api.getDocument(docId) })
  const listQ = useQuery({ queryKey: ['reviews', docId], queryFn: () => api.listReviews(docId) })
  const currentId = reviewId ?? listQ.data?.[0]?.id ?? null
  const key = ['review', currentId]
  const reviewQ = useQuery({
    queryKey: key,
    queryFn: () => api.getReview(currentId!),
    enabled: currentId !== null,
    refetchInterval: (q) =>
      q.state.data && ACTIVE.includes(q.state.data.status) ? POLL_MS : false,
  })
  const review = reviewQ.data
  const comments = review?.comments ?? []
  const doc = docQ.data
  const groups = doc ? inDocumentOrder(doc, applyFilter(comments, filter)) : []
  const visible = groups.flatMap((g) => g.notes)
  const active = comments.find((c) => c.id === activeId) ?? null

  const fail = (e: unknown) => setError(e instanceof ApiError ? e.message : String(e))
  const patchCache = (fn: (cs: ReviewComment[]) => ReviewComment[]) =>
    qc.setQueryData<Review>(key, (r) => (r ? { ...r, comments: fn(r.comments ?? []) } : r))

  const setStatus = useMutation({
    mutationFn: (v: { id: number; status: CommentStatus; mentor_text?: string }) =>
      api.updateComment(
        v.id,
        v.mentor_text === undefined
          ? { status: v.status }
          : { status: v.status, mentor_text: v.mentor_text },
      ),
    onMutate: (v) => {
      setError(null)
      const before = qc.getQueryData<Review>(key)
      patchCache((cs) =>
        cs.map((c) =>
          c.id === v.id
            ? { ...c, status: v.status, mentor_text: v.mentor_text ?? c.mentor_text }
            : c,
        ),
      )
      if (v.status === 'accepted' || v.status === 'edited') setFresh(v.id)
      return { before }
    },
    onError: (e, _v, ctx) => {
      qc.setQueryData(key, ctx?.before)
      fail(e)
    },
    onSuccess: (saved, v) =>
      patchCache((cs) =>
        cs.map((c) =>
          c.id === v.id ? { ...c, status: saved.status, mentor_text: saved.mentor_text } : c,
        ),
      ),
  })

  const bulk = useMutation({
    mutationFn: (ids: number[]) => api.bulkStatus(currentId!, ids, 'accepted'),
    onMutate: (ids) =>
      patchCache((cs) => cs.map((c) => (ids.includes(c.id) ? { ...c, status: 'accepted' } : c))),
    onError: (e) => {
      qc.invalidateQueries({ queryKey: key })
      fail(e)
    },
  })

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteComment(id),
    onSuccess: (_r, id) => patchCache((cs) => cs.filter((c) => c.id !== id)),
    onError: fail,
  })

  const start = useMutation({
    mutationFn: () => api.startReview(docId),
    onSuccess: (r) => {
      setReviewId(r.id)
      qc.invalidateQueries({ queryKey: ['reviews', docId] })
    },
    onError: fail,
  })

  const retry = useMutation({
    mutationFn: () => api.retryReview(currentId!),
    onSuccess: (r) =>
      qc.setQueryData(key, (old: Review | undefined) => ({
        ...old,
        ...r,
        comments: old?.comments ?? [],
      })),
    onError: fail,
  })

  function activate(c: ReviewComment) {
    setActiveId(c.id)
    jump(c.paragraph_id ? `p-${c.paragraph_id}` : c.section_id ? `s-${c.section_id}` : `c-${c.id}`)
  }

  // Mentor speed: j/k move, a accepts, r rejects (ignored while typing).
  const keys = useRef({ visible, active, activate, setStatus })
  keys.current = { visible, active, activate, setStatus }
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement
      if (
        e.metaKey ||
        e.ctrlKey ||
        e.altKey ||
        target.closest('input, textarea, select, [contenteditable]')
      )
        return
      const { visible, active, activate, setStatus } = keys.current
      const i = active ? visible.findIndex((c) => c.id === active.id) : -1
      if (e.key === 'j' && visible.length) activate(visible[Math.min(i + 1, visible.length - 1)])
      else if (e.key === 'k' && visible.length) activate(visible[Math.max(i - 1, 0)])
      else if ((e.key === 'a' || e.key === 'r') && active)
        setStatus.mutate({ id: active.id, status: e.key === 'a' ? 'accepted' : 'rejected' })
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  if (docQ.error) return <p className="page-msg">{(docQ.error as Error).message}</p>
  if (!doc || listQ.isPending) return <p className="page-msg text-graphite">…</p>

  const counts = {
    pending: comments.filter((c) => c.status === 'pending').length,
    confirmed: comments.filter((c) => c.status === 'accepted' || c.status === 'edited').length,
    rejected: comments.filter((c) => c.status === 'rejected').length,
  }
  const running = review && ACTIVE.includes(review.status)
  const visiblePending = visible.filter((c) => c.status === 'pending').map((c) => c.id)

  return (
    <div className="workspace">
      <aside className="pane pane-left">
        <Link to="/" className="back-link">
          {t.review.back}
        </Link>
        <p className="mt-3 text-[13px] text-graphite">
          {doc.filename}, {t.docType[doc.doc_type]}
        </p>
        <div className="mt-4">
          <SummaryPanel doc={doc} summary={review?.summary ?? null} onJump={jump} />
        </div>
      </aside>

      <main className="pane pane-center" aria-label={doc.title ?? doc.filename}>
        {error && (
          <p role="alert" className="alert">
            {error}
          </p>
        )}
        <DocumentViewer
          doc={doc}
          comments={comments}
          active={active}
          figures={review?.figures ?? {}}
          onSelectText={setSelection}
        />
      </main>

      <aside className="pane pane-right" aria-label={t.review.notes}>
        {!review ? (
          <div>
            <p>{t.review.startHint}</p>
            <button
              className="btn btn-ink mt-3"
              disabled={start.isPending}
              onClick={() => start.mutate()}
            >
              {t.review.start}
            </button>
          </div>
        ) : (
          <>
            <ReviewStatus
              review={review}
              running={!!running}
              onRetry={() => retry.mutate()}
              onRerun={() => start.mutate()}
              busy={retry.isPending || start.isPending}
            />

            <div className="mt-5 flex items-baseline justify-between gap-2">
              <h2 className="pane-title">{t.review.notes}</h2>
              <span className="text-[13px] text-graphite">
                {t.review.counts(counts.pending, counts.confirmed, counts.rejected)}
              </span>
            </div>
            <div className="mt-3">
              <IssueFilter filter={filter} onChange={setFilter} />
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              <button
                className="btn"
                disabled={!visiblePending.length || bulk.isPending}
                onClick={() => bulk.mutate(visiblePending)}
              >
                {t.review.acceptVisible}
              </button>
              <button className="btn" onClick={() => setDraft({ pid: null, quote: null })}>
                {t.review.addGeneral}
              </button>
              {selection && (
                <button className="btn btn-ink" onClick={() => setDraft(selection)}>
                  {t.review.addOnSelection}
                </button>
              )}
            </div>
            {draft && (
              <NewNote
                reviewId={review.id}
                draft={draft}
                onDone={(c) => {
                  if (c) {
                    patchCache((cs) => [...cs, c])
                    setActiveId(c.id)
                  }
                  setDraft(null)
                }}
                onError={fail}
              />
            )}
            <p className="mt-3 text-[13px] text-graphite">{t.review.keys}</p>

            {groups.length === 0 && !running && (
              <p className="mt-4 text-graphite">{t.review.noComments}</p>
            )}
            {groups.map((g) => (
              <section key={g.id} className="mt-5">
                <h3 className="group-title">{g.heading ?? t.review.general}</h3>
                <div className="mt-2 space-y-3">
                  {g.notes.map((c) => (
                    <CommentCard
                      key={c.id}
                      c={c}
                      active={c.id === activeId}
                      fresh={c.id === fresh}
                      onActivate={() => activate(c)}
                      onStatus={(status, mentor_text) =>
                        setStatus.mutate({ id: c.id, status, mentor_text })
                      }
                      onDelete={() => remove.mutate(c.id)}
                    />
                  ))}
                </div>
              </section>
            ))}
            {!running && <Overall key={review.id} review={review} onError={fail} />}
          </>
        )}
      </aside>
    </div>
  )
}

function ReviewStatus({
  review,
  running,
  busy,
  onRetry,
  onRerun,
}: {
  review: Review
  running: boolean
  busy: boolean
  onRetry: () => void
  onRerun: () => void
}) {
  const t = useT()
  const failed = review.errors.filter((e) => e.section_id).length
  return (
    <div>
      <p className="flex items-baseline gap-2">
        <span className={`status-dot status-${review.status}`} aria-hidden />
        <span>{t.status[review.status]}</span>
      </p>
      {running && (
        <>
          <div
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress(review.stage)}
            aria-label={stageLabel(t, review.stage)}
            className="progress mt-2"
          >
            <div style={{ width: `${progress(review.stage)}%` }} />
          </div>
          <p className="mt-1 text-[13px] text-graphite">{stageLabel(t, review.stage)}</p>
        </>
      )}
      {review.status === 'partial' && (
        <p className="mt-1 text-[13px]">{t.review.failedSections(failed)}</p>
      )}
      {review.status === 'failed' && review.errors[0] && (
        <p className="mt-1 text-[13px] text-seal">{review.errors[0].error}</p>
      )}
      {!running && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {(review.status === 'partial' || review.status === 'failed') && (
            <button className="btn btn-ink" disabled={busy} onClick={onRetry}>
              {t.review.retry}
            </button>
          )}
          <a className="btn" href={api.exportUrl(review.id, 'docx')} download>
            {t.review.exportDocx}
          </a>
          <a className="btn" href={api.exportUrl(review.id, 'md')} download>
            {t.review.exportMd}
          </a>
          {review.status === 'done' && (
            <button className="btn" disabled={busy} onClick={onRerun}>
              {t.review.rerun}
            </button>
          )}
        </div>
      )}
      {review.warnings.length > 0 && (
        <details className="mt-3 text-[13px] text-graphite">
          <summary className="cursor-pointer">
            {t.review.warnings} ({review.warnings.length})
          </summary>
          <ul className="mt-1 space-y-1">
            {review.warnings.map((w, i) => (
              <li key={i}>{w.replace(/^[A-Z_]+:\s*/, '')}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function Overall({ review, onError }: { review: Review; onError: (e: unknown) => void }) {
  const t = useT()
  const qc = useQueryClient()
  const [text, setText] = useState(review.overall_feedback ?? '')
  const [saved, setSaved] = useState(false)
  const store = (r: Review) => {
    setText(r.overall_feedback ?? '')
    qc.setQueryData<Review>(['review', review.id], (old) =>
      old ? { ...old, overall_feedback: r.overall_feedback } : old,
    )
  }
  const draft = useMutation({
    mutationFn: () => api.generateOverall(review.id),
    onSuccess: store,
    onError,
  })
  const save = useMutation({
    mutationFn: () => api.saveOverall(review.id, text),
    onSuccess: (r) => {
      store(r)
      setSaved(true)
    },
    onError,
  })
  return (
    <section className="mt-5">
      <h2 className="pane-title">{t.review.overall}</h2>
      <p className="mt-1 text-[13px] text-graphite">{t.review.overallHint}</p>
      <textarea
        className="field mt-2 min-h-28 w-full"
        aria-label={t.review.overall}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          setSaved(false)
        }}
      />
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <button className="btn" disabled={draft.isPending} onClick={() => draft.mutate()}>
          {t.review.overallDraft}
        </button>
        <button className="btn btn-ink" disabled={save.isPending} onClick={() => save.mutate()}>
          {t.review.overallSave}
        </button>
        {saved && <span className="text-[13px] text-graphite">{t.review.overallSaved}</span>}
      </div>
    </section>
  )
}

function NewNote({
  reviewId,
  draft,
  onDone,
  onError,
}: {
  reviewId: number
  draft: { pid: string | null; quote: string | null }
  onDone: (c: ReviewComment | null) => void
  onError: (e: unknown) => void
}) {
  const t = useT()
  const [problem, setProblem] = useState('')
  const [suggestion, setSuggestion] = useState('')
  const [category, setCategory] = useState<Category>('clarity')
  const [severity, setSeverity] = useState<Severity>('medium')
  const add = useMutation({
    mutationFn: () =>
      api.addComment(reviewId, {
        paragraph_id: draft.pid,
        quote: draft.quote,
        category,
        severity,
        problem: problem.trim(),
        suggestion: suggestion.trim(),
      }),
    onSuccess: onDone,
    onError,
  })
  return (
    <form
      className="note mt-3"
      data-severity={severity}
      onSubmit={(e) => {
        e.preventDefault()
        if (problem.trim()) add.mutate()
      }}
    >
      <h3 className="text-[13px] text-graphite">
        {t.comment.newTitle}
        {draft.pid && `, ${t.comment.on} ${draft.pid}`}
      </h3>
      {draft.quote && <blockquote className="quote">{draft.quote}</blockquote>}
      <label className="mt-2 block text-[13px] text-graphite" htmlFor="new-problem">
        {t.comment.problem}
      </label>
      <textarea
        id="new-problem"
        className="field min-h-20 w-full"
        value={problem}
        onChange={(e) => setProblem(e.target.value)}
        autoFocus
      />
      <label className="mt-2 block text-[13px] text-graphite" htmlFor="new-suggestion">
        {t.comment.suggestionField}
      </label>
      <textarea
        id="new-suggestion"
        className="field min-h-14 w-full"
        value={suggestion}
        onChange={(e) => setSuggestion(e.target.value)}
      />
      <div className="mt-2 grid grid-cols-2 gap-2">
        <select
          className="field py-1"
          aria-label={t.filter.severity}
          value={severity}
          onChange={(e) => setSeverity(e.target.value as Severity)}
        >
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {t.severity[s]}
            </option>
          ))}
        </select>
        <select
          className="field py-1"
          aria-label={t.filter.category}
          value={category}
          onChange={(e) => setCategory(e.target.value as Category)}
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {t.category[c]}
            </option>
          ))}
        </select>
      </div>
      <div className="mt-2 flex gap-2">
        <button type="submit" className="btn btn-ink" disabled={!problem.trim() || add.isPending}>
          {t.comment.add}
        </button>
        <button type="button" className="btn" onClick={() => onDone(null)}>
          {t.comment.cancel}
        </button>
      </div>
    </form>
  )
}
