import { CATEGORIES, SEVERITIES } from '../api/client'
import type { Filter } from '../lib'
import { useT } from '../strings'

export default function IssueFilter({
  filter,
  onChange,
}: {
  filter: Filter
  onChange: (f: Filter) => void
}) {
  const t = useT()
  const select = (key: keyof Filter, label: string, options: [string, string][]) => (
    <label className="flex flex-col gap-0.5 text-[13px] text-graphite">
      {label}
      <select
        className="field py-1"
        value={filter[key] as string}
        onChange={(e) => onChange({ ...filter, [key]: e.target.value })}
      >
        <option value="">{t.filter.all}</option>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  )
  return (
    <div className="grid grid-cols-2 gap-x-3 gap-y-2">
      {select(
        'severity',
        t.filter.severity,
        SEVERITIES.map((s) => [s, t.severity[s]]),
      )}
      {select(
        'category',
        t.filter.category,
        CATEGORIES.map((c) => [c, t.category[c]]),
      )}
      {select('status', t.filter.status, Object.entries(t.commentStatus))}
      {select('origin', t.filter.origin, Object.entries(t.origin))}
      <label className="col-span-2 flex items-center gap-2 text-[13px]">
        <input
          type="checkbox"
          checked={filter.hideRejected}
          onChange={(e) => onChange({ ...filter, hideRejected: e.target.checked })}
        />
        {t.filter.hideRejected}
      </label>
    </div>
  )
}
