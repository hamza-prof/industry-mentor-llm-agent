import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError, type Prompt } from '../api/client'
import { useLang, useT } from '../strings'
import { formatDate } from '../lib'

const PLACEHOLDER = /\{([A-Za-z_]\w*)\}/g

function placeholders(text: string): Set<string> {
  return new Set([...text.matchAll(PLACEHOLDER)].map((m) => m[1]))
}

export default function PromptsPage() {
  const t = useT()
  const list = useQuery({ queryKey: ['prompts'], queryFn: api.listPrompts })
  const [key, setKey] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null) // here: the editor remounts on save
  const current = list.data?.find((p) => p.key === key) ?? list.data?.[0]

  return (
    <div className="page">
      <h1 className="page-title">{t.prompts.title}</h1>
      <p className="lede">{t.prompts.intro}</p>
      {list.error && <p className="alert mt-4">{(list.error as Error).message}</p>}
      {current && (
        <div className="prompt-layout mt-6">
          <nav aria-label={t.prompts.title}>
            <ul className="space-y-1">
              {list.data!.map((p) => (
                <li key={p.key}>
                  <button
                    className="prompt-tab"
                    aria-current={p.key === current.key || undefined}
                    onClick={() => {
                      setKey(p.key)
                      setMessage(null)
                    }}
                  >
                    {t.prompts.names[p.key] ?? p.key}
                    <span className="block text-[13px] text-graphite">
                      {t.prompts.version(p.active_version)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>
          <Editor
            key={`${current.key}:${current.active_version}`}
            prompt={current}
            message={message}
            setMessage={setMessage}
          />
        </div>
      )}
    </div>
  )
}

function Editor({
  prompt,
  message,
  setMessage,
}: {
  prompt: Prompt
  message: string | null
  setMessage: (m: string | null) => void
}) {
  const t = useT()
  const lang = useLang()
  const qc = useQueryClient()
  const [system, setSystem] = useState(prompt.system)
  const [user, setUser] = useState(prompt.user)
  const [error, setError] = useState<string | null>(null)
  const versions = useQuery({
    queryKey: ['prompt-versions', prompt.key],
    queryFn: () => api.promptVersions(prompt.key),
  })
  const used = placeholders(system + user)
  const missing = prompt.required.filter((v) => !used.has(v))
  const allowed = new Set([...prompt.required, ...prompt.optional])
  const unknown = [...used].filter((v) => !allowed.has(v))

  function onSaved(p: Prompt, text: string) {
    qc.setQueryData<Prompt[]>(['prompts'], (ps) => ps?.map((x) => (x.key === p.key ? p : x)))
    qc.invalidateQueries({ queryKey: ['prompt-versions', p.key] })
    setMessage(text)
  }
  function onFail(e: unknown) {
    if (e instanceof ApiError && e.code === 'PROMPT_INVALID') {
      const { missing = [], unknown = [], errors = [] } = e.extra as Record<string, string[]>
      const parts = [...errors]
      if (missing.length) parts.push(t.prompts.missing(missing))
      if (unknown.length) parts.push(t.prompts.unknown(unknown))
      setError(parts.join(' ') || e.message)
    } else setError(e instanceof ApiError ? e.message : String(e))
  }
  const before = () => {
    setError(null)
    setMessage(null)
  }
  const save = useMutation({
    mutationFn: () => api.savePrompt(prompt.key, system, user),
    onMutate: before,
    onSuccess: (p) => onSaved(p, t.prompts.saved(p.active_version)),
    onError: onFail,
  })
  const reset = useMutation({
    mutationFn: () => api.resetPrompt(prompt.key),
    onMutate: before,
    onSuccess: (p) => onSaved(p, t.prompts.saved(p.active_version)),
    onError: onFail,
  })
  const activate = useMutation({
    mutationFn: (v: number) => api.activatePrompt(prompt.key, v),
    onMutate: before,
    onSuccess: (p) => onSaved(p, t.prompts.version(p.active_version)),
    onError: onFail,
  })

  return (
    <div className="min-w-0">
      <p className="text-graphite">{prompt.description}</p>
      <div className="mt-4">
        <p className="text-[13px] text-graphite">{t.prompts.variables}</p>
        <ul className="mt-1 flex flex-wrap gap-1.5">
          {[...prompt.required, ...prompt.optional].map((v) => {
            const req = prompt.required.includes(v)
            return (
              <li key={v} className="chip" data-required={req} data-present={used.has(v)}>
                {`{${v}}`}
                {req && <span className="sr-only"> ({t.prompts.required})</span>}
              </li>
            )
          })}
        </ul>
      </div>
      <label className="mt-4 block text-[13px] text-graphite" htmlFor="p-system">
        {t.prompts.system}
      </label>
      <textarea
        id="p-system"
        className="field code min-h-28 w-full"
        value={system}
        onChange={(e) => setSystem(e.target.value)}
      />
      <label className="mt-3 block text-[13px] text-graphite" htmlFor="p-user">
        {t.prompts.user}
      </label>
      <textarea
        id="p-user"
        className="field code min-h-64 w-full"
        value={user}
        onChange={(e) => setUser(e.target.value)}
      />
      {(missing.length > 0 || unknown.length > 0) && (
        <p className="mt-2 text-seal">
          {missing.length > 0 && t.prompts.missing(missing)}{' '}
          {unknown.length > 0 && t.prompts.unknown(unknown)}
        </p>
      )}
      {error && (
        <p role="alert" className="alert mt-2">
          {error}
        </p>
      )}
      {message && <p className="mt-2 text-graphite">{message}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn btn-ink" disabled={save.isPending} onClick={() => save.mutate()}>
          {t.prompts.save}
        </button>
        <button
          className="btn"
          disabled={reset.isPending}
          onClick={() => window.confirm(t.prompts.confirmReset) && reset.mutate()}
        >
          {t.prompts.reset}
        </button>
      </div>

      {!!versions.data?.length && (
        <section className="mt-8">
          <h2 className="section-title">{t.prompts.history}</h2>
          <ul className="mt-2 divide-y divide-rule border-y border-rule">
            {versions.data.map((v) => (
              <li key={v.version} className="flex items-baseline gap-3 py-2">
                <span>{t.prompts.version(v.version)}</span>
                <span className="text-[13px] text-graphite">{formatDate(v.created_at, lang)}</span>
                {v.version === prompt.active_version ? (
                  <span className="ml-auto text-[13px] text-graphite">{t.prompts.active}</span>
                ) : (
                  <button className="btn-quiet ml-auto" onClick={() => activate.mutate(v.version)}>
                    {t.prompts.use}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
