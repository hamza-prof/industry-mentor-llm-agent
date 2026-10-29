import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { mockApi, renderAt } from '../test/util'
import KnowledgeBasePage from './KnowledgeBasePage'

afterEach(() => vi.unstubAllGlobals())

const source = {
  id: 1,
  filename: 'rubric.md',
  category: 'standard',
  doc_type: 'any',
  chunk_count: 12,
  embedding_model: 'bge-m3',
  created_at: '2026-10-28T10:00:00',
}

function open(routes = {}, health = { kb_configured: true, kb_needs_reindex: false }) {
  const calls = mockApi({
    'GET /health': () => ({ status: 'ok', llm_configured: true, ...health }),
    'GET /kb/sources': () => [source],
    'POST /kb/sources': () => [
      409,
      { detail: 'Already added.', code: 'DUPLICATE_SOURCE', existing_id: 1 },
    ],
    'GET /kb/search\\?.*': () => [
      {
        chunk_id: '1:0',
        source_id: 1,
        filename: 'rubric.md',
        category: 'standard',
        text: 'Every claim needs data.',
        score: 0.21,
      },
    ],
    ...routes, // last: a test's routes replace the defaults
  })
  renderAt('/kb', <Route path="/kb" element={<KnowledgeBasePage />} />)
  return calls
}

test('lists sources with passage counts', async () => {
  open()
  expect(await screen.findByText('rubric.md')).toBeInTheDocument()
  expect(screen.getByText('12')).toBeInTheDocument()
  expect(screen.getAllByText('Review standard').length).toBeGreaterThan(0)
})

test('duplicate upload shows a clear message', async () => {
  open()
  await screen.findByText('rubric.md')
  await userEvent.upload(screen.getByLabelText('Add source'), new File(['# x'], 'again.md'))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'This file is already in the knowledge base.',
  )
})

test('delete asks first', async () => {
  const calls = open({ 'DELETE /kb/sources/1': () => [204, null] })
  await screen.findByText('rubric.md')
  vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
  await userEvent.click(screen.getByRole('button', { name: 'Delete rubric.md' }))
  expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  await userEvent.click(screen.getByRole('button', { name: 'Delete rubric.md' }))
  await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
})

test('test search shows hits with their distance', async () => {
  const calls = open()
  await screen.findByText('rubric.md')
  await userEvent.type(screen.getByLabelText('Try a search'), 'claims without data')
  await userEvent.click(screen.getByRole('button', { name: 'Search' }))
  expect(await screen.findByText('Every claim needs data.')).toBeInTheDocument()
  expect(screen.getByText(/0\.21/)).toBeInTheDocument()
  expect(calls.find((c) => c.path.startsWith('/kb/search'))?.path).toContain('category=standard')
})

test('not configured explains what to set', async () => {
  open({}, { kb_configured: false, kb_needs_reindex: false })
  expect(await screen.findByText(/Embeddings are not set up/)).toBeInTheDocument()
})
