import { afterEach, expect, test, vi } from 'vitest'
import { api, ApiError, NETWORK_ERROR } from './client'

afterEach(() => vi.unstubAllGlobals())

const reply = (status: number, body: unknown) =>
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  )

test('error JSON becomes an ApiError with code, detail and extra fields', async () => {
  reply(409, { detail: 'A review is already running.', code: 'REVIEW_RUNNING', review_id: 7 })
  const err = await api.startReview(1).catch((e) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect([err.status, err.code, err.message, err.extra.review_id]).toEqual([
    409,
    'REVIEW_RUNNING',
    'A review is already running.',
    7,
  ])
})

test('FastAPI validation errors are joined into one message', async () => {
  reply(422, { detail: [{ msg: 'field required', loc: ['body', 'problem'] }] })
  const err = await api
    .addComment(1, { category: 'clarity', severity: 'low', problem: '' })
    .catch((e) => e)
  expect([err.code, err.message]).toEqual(['INVALID_REQUEST', 'field required'])
})

test('network failure gives a friendly message', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))),
  )
  const err = await api.health().catch((e) => e)
  expect(err.code).toBe(NETWORK_ERROR)
  expect(err.message).toMatch(/not reachable/)
})

test('204 resolves without a body', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(null, { status: 204 })),
  )
  await expect(api.deleteDocument(3)).resolves.toBeUndefined()
})
