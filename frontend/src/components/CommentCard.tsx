import { useState } from 'react'
import type { CommentStatus, ReviewComment } from '../api/client'
import { useT } from '../strings'

export function Seal({ fresh }: { fresh: boolean }) {
  const t = useT()
  return (
    <span
      role="img"
      aria-label={t.comment.accepted}
      className={`seal ${fresh ? 'seal-fresh' : ''}`}
    >
      {t.comment.seal}
    </span>
  )
}

interface Props {
  c: ReviewComment
  active: boolean
  fresh: boolean
  onActivate: () => void
  onStatus: (status: CommentStatus, mentorText?: string) => void
  onDelete: () => void
}

export default function CommentCard({ c, active, fresh, onActivate, onStatus, onDelete }: Props) {
  const t = useT()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [needText, setNeedText] = useState(false)
  const confirmed = c.status === 'accepted' || c.status === 'edited'
  const where = c.paragraph_id ?? c.section_id

  function startEdit() {
    setDraft(c.mentor_text ?? (c.suggestion ? `${c.problem}\n${c.suggestion}` : c.problem))
    setNeedText(false)
    setEditing(true)
  }

  function save() {
    if (!draft.trim()) return setNeedText(true)
    onStatus('edited', draft.trim())
    setEditing(false)
  }

  return (
    <article
      className="note"
      data-severity={c.severity}
      data-status={c.status}
      data-active={active || undefined}
      id={`c-${c.id}`}
      onClick={onActivate}
    >
      <header className="flex items-baseline gap-2 text-[13px] text-graphite">
        <span className="sev-label">{t.severity[c.severity]}</span>
        <span>{t.category[c.category]}</span>
        {where && <span className="pid">{where}</span>}
        {c.origin !== 'ai' && (
          <span>{c.origin === 'mentor' ? t.comment.mine : t.comment.rule}</span>
        )}
        {confirmed && (
          <span className="seal-slot">
            <Seal fresh={fresh} />
          </span>
        )}
      </header>

      {c.status === 'edited' && c.mentor_text && !editing ? (
        <>
          <p className="mt-1.5 whitespace-pre-line">{c.mentor_text}</p>
          <p className="mt-1 text-[13px] text-graphite line-through decoration-rule">{c.problem}</p>
        </>
      ) : (
        !editing && (
          <>
            {c.quote && <blockquote className="quote">{c.quote}</blockquote>}
            <p className={`mt-1.5 ${c.status === 'rejected' ? 'line-through text-graphite' : ''}`}>
              {c.problem}
            </p>
            {c.suggestion && c.status !== 'rejected' && (
              <p className="mt-1.5">
                <span className="text-graphite">{t.comment.suggestion}: </span>
                {c.suggestion}
              </p>
            )}
            {active && c.revision_steps.length > 0 && c.status !== 'rejected' && (
              <>
                <h4 className="mt-2 text-[13px] text-graphite">{t.comment.steps}</h4>
                <ol className="steps">
                  {c.revision_steps.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ol>
              </>
            )}
            {active && c.standard_refs.length > 0 && (
              <details className="mt-2 text-[13px]" onClick={(e) => e.stopPropagation()}>
                <summary className="cursor-pointer text-graphite">
                  {t.comment.sources} ({c.standard_refs.length})
                </summary>
                <ul className="mt-1 space-y-1 text-graphite">
                  {c.standard_refs.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )
      )}

      {editing && (
        <div className="mt-2" onClick={(e) => e.stopPropagation()}>
          <textarea
            className="field min-h-24 w-full"
            value={draft}
            placeholder={t.comment.editPlaceholder}
            aria-label={t.comment.edit}
            onChange={(e) => setDraft(e.target.value)}
            autoFocus
          />
          {needText && <p className="mt-1 text-[13px] text-seal">{t.comment.needText}</p>}
          <div className="mt-2 flex gap-2">
            <button className="btn btn-ink" onClick={save}>
              {t.comment.save}
            </button>
            <button className="btn" onClick={() => setEditing(false)}>
              {t.comment.cancel}
            </button>
          </div>
        </div>
      )}

      {!editing && (
        <div className="mt-2 flex flex-wrap gap-1.5" onClick={(e) => e.stopPropagation()}>
          {c.status === 'pending' ? (
            <>
              <button className="btn btn-ink" onClick={() => onStatus('accepted')}>
                {t.comment.accept}
              </button>
              <button className="btn" onClick={startEdit}>
                {t.comment.edit}
              </button>
              <button className="btn" onClick={() => onStatus('rejected')}>
                {t.comment.reject}
              </button>
            </>
          ) : (
            <>
              <button className="btn" onClick={() => onStatus('pending')}>
                {t.comment.undo}
              </button>
              {c.status !== 'rejected' && (
                <button className="btn" onClick={startEdit}>
                  {t.comment.edit}
                </button>
              )}
            </>
          )}
          {c.origin === 'mentor' && (
            <button className="btn ml-auto" onClick={onDelete}>
              {t.comment.delete}
            </button>
          )}
        </div>
      )}
    </article>
  )
}
