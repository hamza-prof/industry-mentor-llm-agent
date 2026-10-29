import { useState, type ReactNode } from 'react'
import {
  api,
  SEVERITIES,
  type DocumentOut,
  type FigureDescription,
  type Paragraph,
  type ReviewComment,
  type Severity,
} from '../api/client'
import { useT } from '../strings'

interface Props {
  doc: DocumentOut
  comments: ReviewComment[]
  active: ReviewComment | null
  figures: Record<string, FigureDescription>
  onSelectText: (sel: { pid: string; quote: string } | null) => void
}

function worst(cs: ReviewComment[]): Severity | undefined {
  return SEVERITIES.find((s) => cs.some((c) => c.severity === s))
}

function marked(text: string, quote: string | null | undefined): ReactNode {
  const at = quote ? text.indexOf(quote) : -1
  if (!quote || at < 0) return <span>{text}</span>
  return (
    <span>
      {text.slice(0, at)}
      <mark>{quote}</mark>
      {text.slice(at + quote.length)}
    </span>
  )
}

/** "categories: a, b\nseries: 1, 2" (from the DOCX chart XML) → rows of cells. */
function chartRows(data: string): string[][] {
  return data
    .split('\n')
    .slice(1)
    .map((line) => {
      const [name, values = ''] = line.split(/:\s(.*)/)
      return [name, ...values.split(', ')]
    })
}

export default function DocumentViewer({ doc, comments, active, figures, onSelectText }: Props) {
  const t = useT()
  const [open, setOpen] = useState<Paragraph | null>(null)
  const live = comments.filter((c) => c.status !== 'rejected')
  // ponytail: renders every paragraph; virtualise the list if 300+ paragraph documents lag

  function onMouseUp() {
    const sel = window.getSelection()
    const quote = sel?.toString().trim() ?? ''
    const from = sel?.anchorNode?.parentElement?.closest<HTMLElement>('[data-pid]')
    const to = sel?.focusNode?.parentElement?.closest<HTMLElement>('[data-pid]')
    onSelectText(quote && from && from === to ? { pid: from.dataset.pid!, quote } : null)
  }

  return (
    <div className="paper" lang={doc.language === 'zh' ? 'zh-CN' : 'en'} onMouseUp={onMouseUp}>
      <h1 className="doc-title">{doc.title ?? doc.filename}</h1>
      {doc.sections.map((s) => {
        const sectionNotes = live.filter((c) => c.section_id === s.id && !c.paragraph_id)
        const H = s.level <= 1 ? 'h2' : 'h3'
        return (
          <section key={s.id} aria-labelledby={`s-${s.id}`}>
            {s.id !== 'S0' && (
              <H
                id={`s-${s.id}`}
                className="doc-heading"
                data-severity={worst(sectionNotes)}
                data-active={
                  (active && !active.paragraph_id && active.section_id === s.id) || undefined
                }
              >
                {s.heading}
              </H>
            )}
            {s.paragraphs.map((p) => {
              const notes = live.filter((c) => c.paragraph_id === p.id)
              const isActive = active?.paragraph_id === p.id
              const common = {
                id: `p-${p.id}`,
                'data-pid': p.id,
                'data-severity': worst(notes),
                'data-active': isActive || undefined,
                className: `para para-${p.kind}`,
              }
              if (p.kind === 'figure' && p.figure) {
                const f = p.figure
                const caption = f.caption ?? f.alt_text ?? t.review.figure
                return (
                  <figure key={p.id} {...common}>
                    <button
                      className="figure-btn"
                      onClick={() => setOpen(p)}
                      aria-label={`${t.review.figure}: ${caption}`}
                    >
                      {f.file ? (
                        <img src={api.figureUrl(doc.id, f.image_id)} alt={caption} loading="lazy" />
                      ) : f.chart_data ? (
                        <ChartTable data={f.chart_data} />
                      ) : null}
                    </button>
                    <figcaption>
                      {caption}
                      {!f.analysable && <span className="badge">{t.review.notAnalysed}</span>}
                    </figcaption>
                    <small className="pid">{p.id}</small>
                  </figure>
                )
              }
              return (
                <div key={p.id} {...common}>
                  {p.kind === 'table' ? (
                    <pre className="whitespace-pre-wrap font-serif">
                      {marked(p.text, isActive ? active?.quote : null)}
                    </pre>
                  ) : (
                    marked(p.text, isActive ? active?.quote : null)
                  )}
                  <small className="pid">{p.id}</small>
                </div>
              )
            })}
          </section>
        )
      })}

      {open?.figure && (
        <FigureDialog
          docId={doc.id}
          p={open}
          description={figures[open.figure.image_id]}
          onClose={() => setOpen(null)}
        />
      )}
    </div>
  )
}

function ChartTable({ data }: { data: string }) {
  const rows = chartRows(data)
  return (
    <table className="chart-table">
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            {r.map((cell, j) => (j === 0 ? <th key={j}>{cell}</th> : <td key={j}>{cell}</td>))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function FigureDialog({
  docId,
  p,
  description,
  onClose,
}: {
  docId: number
  p: Paragraph
  description?: FigureDescription
  onClose: () => void
}) {
  const t = useT()
  const f = p.figure!
  return (
    <div className="scrim" onClick={onClose} onKeyDown={(e) => e.key === 'Escape' && onClose()}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={f.caption ?? t.review.figure}
        className="lightbox"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="font-serif text-[21px]">{f.caption ?? t.review.figure}</h2>
          <button className="btn" onClick={onClose} autoFocus>
            {t.review.close}
          </button>
        </div>
        {f.file && (
          <img
            className="mt-3 max-h-[60vh] w-auto"
            src={api.figureUrl(docId, f.image_id)}
            alt={f.caption ?? ''}
          />
        )}
        {f.chart_data && (
          <>
            <h3 className="mt-4 text-[13px] text-graphite">{t.review.chartData}</h3>
            <ChartTable data={f.chart_data} />
          </>
        )}
        <h3 className="mt-4 text-[13px] text-graphite">{t.review.figureNotes}</h3>
        {description ? (
          <>
            <p className="mt-1">{description.summary}</p>
            {description.key_data.length > 0 && (
              <>
                <h3 className="mt-3 text-[13px] text-graphite">{t.review.keyData}</h3>
                <ul className="mt-1 list-disc pl-5">
                  {description.key_data.map((d, i) => (
                    <li key={i}>{d}</li>
                  ))}
                </ul>
              </>
            )}
          </>
        ) : (
          <p className="mt-1 text-graphite">{t.review.noDescription}</p>
        )}
      </div>
    </div>
  )
}
