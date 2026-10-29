import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import {
  api,
  ApiError,
  type AppSettings,
  type Provider,
  type SettingsPatch,
  type TestTarget,
} from '../api/client'
import { useT } from '../strings'

type Group = 'llm' | 'vision' | 'embedding'
type Form = {
  llm_provider: Provider
  llm_base_url: string
  llm_model: string
  vision_provider: Provider | ''
  vision_base_url: string
  vision_model: string
  embedding_provider: AppSettings['embedding_provider']
  embedding_base_url: string
  embedding_model: string
}
type Result = { ok: true } | { ok: false; error: string }

const PROVIDERS: Provider[] = ['openai_compatible', 'openrouter', 'groq', 'anthropic']
const OPENAI_URL = 'https://api.openai.com/v1'
// Common services; picking one fills provider, address and (if given) model.
const PRESETS: { name: string; provider: Provider; base_url: string; model?: string }[] = [
  { name: 'DeepSeek', provider: 'openai_compatible', base_url: 'https://api.deepseek.com', model: 'deepseek-chat' },
  { name: 'Qwen (DashScope)', provider: 'openai_compatible', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  { name: 'Ollama Cloud', provider: 'openai_compatible', base_url: 'https://ollama.com/v1' },
  { name: 'Ollama (this computer)', provider: 'openai_compatible', base_url: 'http://localhost:11434/v1', model: 'qwen2.5:14b' },
  { name: 'OpenAI', provider: 'openai_compatible', base_url: '', model: 'gpt-4o-mini' },
  { name: 'OpenRouter', provider: 'openrouter', base_url: '', model: 'deepseek/deepseek-chat' },
  { name: 'Groq', provider: 'groq', base_url: '', model: 'llama-3.3-70b-versatile' },
  { name: 'Claude', provider: 'anthropic', base_url: '', model: 'claude-sonnet-5-5' },
] // prettier-ignore

const toForm = (s: AppSettings): Form => ({
  llm_provider: s.llm_provider,
  llm_base_url: s.llm_base_url,
  llm_model: s.llm_model,
  vision_provider: s.vision_provider ?? '',
  vision_base_url: s.vision_base_url,
  vision_model: s.vision_model,
  embedding_provider: s.embedding_provider,
  embedding_base_url: s.embedding_base_url,
  embedding_model: s.embedding_model,
})

export default function SettingsPage() {
  const t = useT()
  const settings = useQuery({ queryKey: ['settings'], queryFn: api.getSettings })
  return (
    <div className="page">
      <h1 className="page-title">{t.settings.title}</h1>
      <p className="lede">{t.settings.intro}</p>
      {settings.error && (
        <p role="alert" className="alert mt-4">
          {String((settings.error as Error).message)}
        </p>
      )}
      {settings.data && <SettingsForm initial={settings.data} />}
    </div>
  )
}

function SettingsForm({ initial }: { initial: AppSettings }) {
  const t = useT()
  const qc = useQueryClient()
  const [saved, setSaved] = useState(initial)
  const [form, setForm] = useState(() => toForm(initial))
  const [keys, setKeys] = useState<Record<Group, string>>({ llm: '', vision: '', embedding: '' })
  const [results, setResults] = useState<Partial<Record<Group, Result>>>({})
  const [message, setMessage] = useState<Result | null>(null)
  const set = (patch: Partial<Form>) => {
    setForm((f) => ({ ...f, ...patch }))
    setMessage(null)
  }

  const applied = (s: AppSettings) => {
    setSaved(s)
    qc.setQueryData(['settings'], s)
    qc.invalidateQueries({ queryKey: ['health'] })
  }
  const fail = (e: unknown): Result => ({
    ok: false,
    error: e instanceof ApiError ? e.message : String(e),
  })

  async function saveAll() {
    const patch: SettingsPatch = { ...form }
    for (const g of ['llm', 'vision', 'embedding'] as Group[])
      if (keys[g].trim()) patch[`${g}_api_key`] = keys[g].trim()
    const s = await api.saveSettings(patch)
    applied(s)
    setKeys({ llm: '', vision: '', embedding: '' })
    return s
  }
  const save = useMutation({
    mutationFn: saveAll,
    onSuccess: () => setMessage({ ok: true }),
    onError: (e) => setMessage(fail(e)),
  })
  const removeKey = useMutation({
    mutationFn: (g: Group) => api.saveSettings({ [`${g}_api_key`]: '' }),
    onSuccess: applied,
    onError: (e) => setMessage(fail(e)),
  })
  const test = useMutation({
    mutationFn: async (g: Group) => {
      await saveAll()
      await api.testConnection((g === 'embedding' ? 'embeddings' : g) as TestTarget)
    },
    onMutate: (g) => setResults((r) => ({ ...r, [g]: undefined })),
    onSuccess: (_, g) => setResults((r) => ({ ...r, [g]: { ok: true } })),
    onError: (e, g) => setResults((r) => ({ ...r, [g]: fail(e) })),
  })
  const busy = save.isPending || test.isPending || removeKey.isPending

  const defaultUrl = (p: Provider | '') =>
    p === 'anthropic' ? 'api.anthropic.com' : (saved.default_urls[p] ?? OPENAI_URL)
  const providers = PROVIDERS.includes(form.llm_provider)
    ? PROVIDERS
    : [...PROVIDERS, form.llm_provider]

  const keyField = (g: Group, hint?: string) => (
    <KeyField
      group={g}
      value={keys[g]}
      onChange={(v) => setKeys((k) => ({ ...k, [g]: v }))}
      isSet={saved[`${g}_api_key_set`]}
      last4={saved[`${g}_api_key_hint`]}
      hint={hint}
      busy={busy}
      onRemove={() => removeKey.mutate(g)}
    />
  )
  const testRow = (g: Group) => {
    const r = results[g]
    return (
      <div className="settings-test">
        <button type="button" className="btn" disabled={busy} onClick={() => test.mutate(g)}>
          {test.isPending && test.variables === g ? t.settings.testing : t.settings.test}
        </button>
        {r?.ok && <span className="test-ok">{t.settings.ok}</span>}
        {r && !r.ok && (
          <span role="alert" className="alert">
            {r.error}
          </span>
        )}
      </div>
    )
  }

  return (
    <form
      className="settings mt-8"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <Group title={t.settings.llm.title} hint={t.settings.llm.hint}>
        <Row label={t.settings.preset} id="llm-preset">
          <select
            id="llm-preset"
            className="field"
            value=""
            onChange={(e) => {
              const p = PRESETS.find((x) => x.name === e.target.value)
              if (p)
                set({
                  llm_provider: p.provider,
                  llm_base_url: p.base_url,
                  ...(p.model ? { llm_model: p.model } : {}),
                })
            }}
          >
            <option value="">{t.settings.presetNone}</option>
            {PRESETS.map((p) => (
              <option key={p.name}>{p.name}</option>
            ))}
          </select>
        </Row>
        <Row label={t.settings.provider} id="llm-provider">
          <select
            id="llm-provider"
            className="field"
            value={form.llm_provider}
            onChange={(e) => set({ llm_provider: e.target.value as Provider })}
          >
            {providers.map((p) => (
              <option key={p} value={p}>
                {t.settings.providers[p] ?? p}
              </option>
            ))}
          </select>
        </Row>
        <Row label={t.settings.baseUrl} id="llm-url">
          <input
            id="llm-url"
            className="field"
            value={form.llm_base_url}
            placeholder={t.settings.defaultUrl(defaultUrl(form.llm_provider))}
            onChange={(e) => set({ llm_base_url: e.target.value })}
          />
        </Row>
        <Row label={t.settings.model} id="llm-model">
          <input
            id="llm-model"
            className="field"
            value={form.llm_model}
            onChange={(e) => set({ llm_model: e.target.value })}
          />
        </Row>
        {keyField('llm')}
        {testRow('llm')}
      </Group>

      <Group title={t.settings.vision.title} hint={t.settings.vision.hint}>
        <Row label={t.settings.model} id="vision-model" hint={t.settings.vision.modelHint}>
          <input
            id="vision-model"
            className="field"
            value={form.vision_model}
            onChange={(e) => set({ vision_model: e.target.value })}
          />
        </Row>
        <Row label={t.settings.provider} id="vision-provider">
          <select
            id="vision-provider"
            className="field"
            value={form.vision_provider}
            onChange={(e) => set({ vision_provider: e.target.value as Provider | '' })}
          >
            <option value="">{t.settings.vision.same}</option>
            {PROVIDERS.map((p) => (
              <option key={p} value={p}>
                {t.settings.providers[p]}
              </option>
            ))}
          </select>
        </Row>
        <Row label={t.settings.baseUrl} id="vision-url">
          <input
            id="vision-url"
            className="field"
            value={form.vision_base_url}
            placeholder={t.settings.vision.same}
            onChange={(e) => set({ vision_base_url: e.target.value })}
          />
        </Row>
        {keyField('vision', t.settings.vision.reuseKey)}
        {testRow('vision')}
      </Group>

      <Group title={t.settings.embedding.title} hint={t.settings.embedding.hint}>
        <Row label={t.settings.provider} id="embedding-provider">
          <select
            id="embedding-provider"
            className="field"
            value={form.embedding_provider}
            onChange={(e) =>
              set({ embedding_provider: e.target.value as Form['embedding_provider'] })
            }
          >
            {(['openai_compatible', 'huggingface'] as const).map((p) => (
              <option key={p} value={p}>
                {t.settings.embedding.providers[p]}
              </option>
            ))}
          </select>
        </Row>
        <Row label={t.settings.baseUrl} id="embedding-url">
          <input
            id="embedding-url"
            className="field"
            value={form.embedding_base_url}
            placeholder={t.settings.defaultUrl(OPENAI_URL)}
            disabled={form.embedding_provider === 'huggingface'}
            onChange={(e) => set({ embedding_base_url: e.target.value })}
          />
        </Row>
        <Row label={t.settings.model} id="embedding-model">
          <input
            id="embedding-model"
            className="field"
            value={form.embedding_model}
            onChange={(e) => set({ embedding_model: e.target.value })}
          />
        </Row>
        {form.embedding_provider !== 'huggingface' &&
          keyField('embedding', t.settings.embedding.reuseKey)}
        {testRow('embedding')}
      </Group>

      <div className="settings-actions">
        <button className="btn btn-ink" disabled={busy}>
          {save.isPending ? t.settings.saving : t.settings.save}
        </button>
        {message?.ok && (
          <span role="status" className="test-ok">
            {t.settings.saved}
          </span>
        )}
        {message && !message.ok && (
          <span role="alert" className="alert">
            {message.error}
          </span>
        )}
      </div>
    </form>
  )
}

function Group({ title, hint, children }: { title: string; hint: string; children: ReactNode }) {
  return (
    <fieldset className="settings-group">
      <legend className="sr-only">{title}</legend>
      <div>
        <h2 className="section-title" aria-hidden>
          {title}
        </h2>
        <p className="mt-1 text-[14px] text-graphite">{hint}</p>
      </div>
      <div className="settings-fields">{children}</div>
    </fieldset>
  )
}

function Row({
  label,
  id,
  hint,
  children,
}: {
  label: string
  id: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div className="settings-row">
      <label htmlFor={id}>{label}</label>
      <div className="flex flex-col gap-1">
        {children}
        {hint && <p className="text-[13px] text-graphite">{hint}</p>}
      </div>
    </div>
  )
}

function KeyField(props: {
  group: Group
  value: string
  onChange: (v: string) => void
  isSet: boolean
  last4: string
  hint?: string
  busy: boolean
  onRemove: () => void
}) {
  const t = useT()
  const [shown, setShown] = useState(false)
  const id = `${props.group}-key`
  // with nothing saved, a "falls back to the language model key" hint says more than "no key"
  const status = props.isSet
    ? t.settings.keySaved(props.last4)
    : props.hint
      ? ''
      : t.settings.keyNone
  return (
    <Row label={t.settings.key} id={id} hint={props.isSet ? undefined : props.hint}>
      <div className="flex gap-1.5">
        <input
          id={id}
          className="field flex-1"
          type={shown ? 'text' : 'password'}
          autoComplete="off"
          spellCheck={false}
          value={props.value}
          placeholder={t.settings.keyPlaceholder}
          aria-describedby={`${id}-status`}
          onChange={(e) => props.onChange(e.target.value)}
        />
        <button type="button" className="btn" onClick={() => setShown((s) => !s)}>
          {shown ? t.settings.hide : t.settings.show}
        </button>
      </div>
      <p id={`${id}-status`} className="text-[13px] text-graphite">
        {status}{' '}
        {props.isSet && (
          <button
            type="button"
            className="btn-quiet underline"
            disabled={props.busy}
            aria-label={t.settings.removeKeyLabel(t.settings[props.group].name)}
            onClick={props.onRemove}
          >
            {t.settings.removeKey}
          </button>
        )}
      </p>
    </Row>
  )
}
