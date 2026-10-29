import type { DocumentOut, StructuredSummary } from '../api/client'
import { useT } from '../strings'

const FIELDS = [
  'research_problem',
  'objectives',
  'technical_approach',
  'main_conclusions',
  'innovations',
  'limitations',
] as const

interface Props {
  doc: DocumentOut
  summary: StructuredSummary | null
  onJump: (elementId: string) => void
}

export default function SummaryPanel({ doc, summary, onJump }: Props) {
  const t = useT()
  const oneLine = new Map(summary?.outline.map((o) => [o.section_id, o.one_line]))
  return (
    <div className="space-y-6">
      {summary && (
        <section>
          <h2 className="pane-title">{t.review.summary}</h2>
          <dl className="mt-3 space-y-3">
            {FIELDS.map((f) => {
              const v = summary[f]
              return (
                <div key={f}>
                  <dt className="text-[13px] text-graphite">{t.fields[f]}</dt>
                  <dd className={v.not_found || !v.text ? 'text-graphite italic' : ''}>
                    {v.text ?? t.review.notFound}
                    {v.source_ids.map((id) => (
                      <button key={id} className="pid-link" onClick={() => onJump(`p-${id}`)}>
                        {id}
                      </button>
                    ))}
                  </dd>
                </div>
              )
            })}
          </dl>
        </section>
      )}
      <nav aria-label={t.review.outline}>
        <h2 className="pane-title">{t.review.outline}</h2>
        <ol className="mt-2 space-y-1">
          {doc.sections
            .filter((s) => s.id !== 'S0')
            .map((s) => (
              <li key={s.id} style={{ paddingLeft: `${(s.level - 1) * 0.75}rem` }}>
                <button className="outline-link" onClick={() => onJump(`s-${s.id}`)}>
                  {s.heading}
                </button>
                {oneLine.get(s.id) && (
                  <p className="text-[13px] text-graphite">{oneLine.get(s.id)}</p>
                )}
              </li>
            ))}
        </ol>
      </nav>
    </div>
  )
}
