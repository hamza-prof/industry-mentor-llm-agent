// Typed wrapper around the backend API. Types mirror backend/app/schemas.py and the API models.
// ponytail: hand-written types; generate them from /openapi.json with openapi-typescript if they drift

export type DocType = 'report' | 'proposal' | 'technical'
export type Severity = 'high' | 'medium' | 'low'
export type Category =
  | 'evidence'
  | 'feasibility'
  | 'logic'
  | 'format'
  | 'completeness'
  | 'clarity'
  | 'innovation'
  | 'citation'
export type CommentStatus = 'pending' | 'accepted' | 'edited' | 'rejected'
export type Origin = 'ai' | 'rule' | 'mentor'
export type ReviewStatus = 'queued' | 'running' | 'done' | 'partial' | 'failed'
export type KBCategory = 'standard' | 'program_requirement' | 'exemplar'

export const CATEGORIES: Category[] = [
  'evidence',
  'feasibility',
  'logic',
  'format',
  'completeness',
  'clarity',
  'innovation',
  'citation',
]
export const SEVERITIES: Severity[] = ['high', 'medium', 'low']

export interface Figure {
  image_id: string
  file: string | null
  source: 'embedded' | 'docx_chart' | 'pdf_vector'
  caption: string | null
  alt_text: string | null
  chart_data: string | null
  analysable: boolean
}

export interface Paragraph {
  id: string
  text: string
  page: number | null
  kind: 'text' | 'table' | 'list' | 'figure'
  figure: Figure | null
}

export interface Section {
  id: string
  heading: string
  level: number
  paragraphs: Paragraph[]
}

export interface DocumentOut {
  id: number
  filename: string
  doc_type: DocType
  language: 'zh' | 'en'
  title: string | null
  sections: Section[]
  warnings: string[]
  figure_count: number
  char_count: number
  created_at: string
  duplicate: boolean
}

export interface DocumentSummary {
  id: number
  filename: string
  doc_type: DocType
  language: 'zh' | 'en'
  created_at: string
  section_count: number
  figure_count: number
  latest_review: { id: number; status: ReviewStatus; stage: string } | null
}

export interface SummaryField {
  text: string | null
  not_found: boolean
  source_ids: string[]
}

export interface StructuredSummary {
  research_problem: SummaryField
  objectives: SummaryField
  technical_approach: SummaryField
  main_conclusions: SummaryField
  innovations: SummaryField
  limitations: SummaryField
  outline: { section_id: string; heading: string; one_line: string }[]
  title: string | null
  warnings: string[]
}

export interface FigureDescription {
  kind: string
  summary: string
  key_data: string[]
  readable: boolean
  issues: string[]
}

export interface ReviewComment {
  id: number
  section_id: string | null
  paragraph_id: string | null
  quote: string | null
  anchored: boolean
  category: Category
  severity: Severity
  problem: string
  suggestion: string
  revision_steps: string[]
  standard_refs: string[]
  origin: Origin
  status: CommentStatus
  mentor_text: string | null
}

export interface Review {
  id: number
  document_id: number
  status: ReviewStatus
  stage: string
  model: string
  errors: { section_id: string | null; error: string }[]
  warnings: string[]
  summary: StructuredSummary | null
  figures_analysed: number
  overall_feedback: string | null
  created_at: string
  comment_count: number
  comments: ReviewComment[] | null
  figures: Record<string, FigureDescription> | null
}

export interface Health {
  status: string
  llm_configured: boolean
  vision_configured: boolean
  kb_configured: boolean
  kb_needs_reindex: boolean
  max_upload_mb?: number
}

export type Provider = 'openai_compatible' | 'openrouter' | 'groq' | 'anthropic' | 'fake'

/** API keys are never returned: only whether one is saved and its last 4 characters. */
export interface AppSettings {
  llm_provider: Provider
  llm_base_url: string
  llm_model: string
  vision_provider: Provider | null
  vision_base_url: string
  vision_model: string
  embedding_provider: 'openai_compatible' | 'huggingface'
  embedding_base_url: string
  embedding_model: string
  llm_api_key_set: boolean
  llm_api_key_hint: string
  vision_api_key_set: boolean
  vision_api_key_hint: string
  embedding_api_key_set: boolean
  embedding_api_key_hint: string
  default_urls: Record<string, string>
}

/** Omitted = unchanged; an API key of '' removes it. */
export type SettingsPatch = Partial<
  Omit<AppSettings, `${string}_set` | `${string}_hint` | 'default_urls' | 'vision_provider'> & {
    vision_provider: Provider | ''
    llm_api_key: string
    vision_api_key: string
    embedding_api_key: string
  }
>

export type TestTarget = 'llm' | 'vision' | 'embeddings'

export interface Prompt {
  key: string
  description: string
  required: string[]
  optional: string[]
  active_version: number
  system: string
  user: string
}

export interface PromptVersion {
  version: number
  system: string
  user: string
  created_at: string
}

export interface KBSource {
  id: number
  filename: string
  category: KBCategory
  doc_type: string
  chunk_count: number
  embedding_model: string
  created_at: string
}

export interface KBHit {
  chunk_id: string
  source_id: number
  filename: string
  category: string
  text: string
  score: number
}

export interface NewComment {
  paragraph_id?: string | null
  section_id?: string | null
  quote?: string | null
  category: Category
  severity: Severity
  problem: string
  suggestion?: string
}

export class ApiError extends Error {
  status: number
  code: string
  extra: Record<string, unknown>

  constructor(status: number, code: string, detail: string, extra: Record<string, unknown> = {}) {
    super(detail)
    this.status = status
    this.code = code
    this.extra = extra
  }
}

export const NETWORK_ERROR = 'NETWORK_ERROR'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, init)
  } catch {
    throw new ApiError(0, NETWORK_ERROR, 'The server is not reachable. Is the backend running?')
  }
  if (res.status === 204) return undefined as T
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    if (body && typeof body.detail === 'string') {
      const { detail, code, ...extra } = body
      throw new ApiError(res.status, code ?? 'ERROR', detail, extra)
    }
    // FastAPI's own validation errors: {"detail": [{msg, loc}, …]}
    const msg = Array.isArray(body?.detail)
      ? body.detail.map((d: { msg: string }) => d.msg).join('; ')
      : res.statusText
    throw new ApiError(res.status, 'INVALID_REQUEST', msg || `Request failed (${res.status})`)
  }
  return body as T
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
})

function form(fields: Record<string, string | Blob>): RequestInit {
  const data = new FormData()
  for (const [k, v] of Object.entries(fields)) data.append(k, v)
  return { method: 'POST', body: data }
}

export const api = {
  health: () => request<Health>('/health'),

  getSettings: () => request<AppSettings>('/settings'),
  saveSettings: (patch: SettingsPatch) => request<AppSettings>('/settings', json('PUT', patch)),
  testConnection: (target: TestTarget) =>
    request<{ ok: boolean }>('/settings/test', json('POST', { target })),

  listDocuments: () => request<DocumentSummary[]>('/documents'),
  getDocument: (id: number) => request<DocumentOut>(`/documents/${id}`),
  uploadDocument: (file: File, docType: DocType) =>
    request<DocumentOut>('/documents', form({ file, doc_type: docType })),
  deleteDocument: (id: number) => request<void>(`/documents/${id}`, { method: 'DELETE' }),
  figureUrl: (docId: number, imageId: string) => `/api/documents/${docId}/figures/${imageId}`,

  listReviews: (docId: number) => request<Review[]>(`/documents/${docId}/reviews`),
  getReview: (id: number) => request<Review>(`/reviews/${id}`),
  startReview: (docId: number) => request<Review>('/reviews', json('POST', { document_id: docId })),
  retryReview: (id: number) => request<Review>(`/reviews/${id}/retry`, json('POST')),
  generateOverall: (id: number) => request<Review>(`/reviews/${id}/overall`, json('POST')),
  saveOverall: (id: number, text: string) =>
    request<Review>(`/reviews/${id}/overall`, json('PUT', { text })),
  exportUrl: (id: number, format: 'md' | 'docx') => `/api/reviews/${id}/export?format=${format}`,

  updateComment: (
    id: number,
    patch: Partial<Pick<ReviewComment, 'status' | 'mentor_text' | 'severity' | 'category'>>,
  ) => request<ReviewComment>(`/comments/${id}`, json('PATCH', patch)),
  addComment: (reviewId: number, body: NewComment) =>
    request<ReviewComment>(`/reviews/${reviewId}/comments`, json('POST', body)),
  deleteComment: (id: number) => request<void>(`/comments/${id}`, { method: 'DELETE' }),
  bulkStatus: (reviewId: number, ids: number[], status: 'pending' | 'accepted' | 'rejected') =>
    request<ReviewComment[]>(`/reviews/${reviewId}/comments/bulk`, json('POST', { ids, status })),

  listPrompts: () => request<Prompt[]>('/prompts'),
  savePrompt: (key: string, system: string, user: string) =>
    request<Prompt>(`/prompts/${key}`, json('PUT', { system, user })),
  resetPrompt: (key: string) => request<Prompt>(`/prompts/${key}/reset`, json('POST')),
  promptVersions: (key: string) => request<PromptVersion[]>(`/prompts/${key}/versions`),
  activatePrompt: (key: string, version: number) =>
    request<Prompt>(`/prompts/${key}/activate/${version}`, json('POST')),

  listSources: () => request<KBSource[]>('/kb/sources'),
  addSource: (file: File, category: KBCategory, docType: string) =>
    request<KBSource>('/kb/sources', form({ file, category, doc_type: docType })),
  deleteSource: (id: number) => request<void>(`/kb/sources/${id}`, { method: 'DELETE' }),
  searchKB: (q: string, category: KBCategory) =>
    request<KBHit[]>(`/kb/search?${new URLSearchParams({ q, category })}`),
  reindexKB: () => request<{ reindexed: number }>('/kb/reindex', json('POST')),
}
