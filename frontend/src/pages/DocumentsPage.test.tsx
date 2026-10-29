import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, useParams } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import type { DocumentSummary } from '../api/client'
import { doc } from '../test/fixtures'
import { mockApi, renderAt } from '../test/util'
import DocumentsPage from './DocumentsPage'

afterEach(() => vi.unstubAllGlobals())

const row = (over: Partial<DocumentSummary> = {}): DocumentSummary => ({
  id: 1,
  filename: 'report.md',
  doc_type: 'report',
  language: 'en',
  created_at: '2026-10-28T10:00:00',
  section_count: 2,
  figure_count: 1,
  latest_review: { id: 10, status: 'done', stage: 'done' },
  ...over,
})

function open(routes = {}) {
  let docs = [row()]
  const calls = mockApi({
    'GET /health': () => ({ status: 'ok', llm_configured: true, max_upload_mb: 1 }),
    'GET /documents': () => docs,
    'POST /documents': () => {
      docs = [row({ id: 2, filename: 'new.md', latest_review: null }), ...docs]
      return [201, { ...doc, id: 2, filename: 'new.md' }]
    },
    ...routes, // last: a test's routes replace the defaults
  })
  renderAt(
    '/',
    <>
      <Route path="/" element={<DocumentsPage />} />
      <Route path="/documents/:id" element={<ReviewStub />} />
    </>,
  )
  return calls
}

function ReviewStub() {
  return <p>review page /documents/{useParams().id}</p>
}

const file = (name: string, size = 10) => new File(['x'.repeat(size)], name)

test('lists documents with their review status', async () => {
  open()
  expect(await screen.findByText('report.md')).toBeInTheDocument()
  expect(screen.getByText('Reviewed')).toBeInTheDocument()
  expect(screen.getByRole('cell', { name: 'Practice report' })).toBeInTheDocument()
})

test('wrong file type and oversized files are refused before upload', async () => {
  const calls = open()
  await screen.findByText('report.md')
  const input = screen.getByLabelText(/choose a file/i)
  await userEvent.upload(input, file('notes.exe'), { applyAccept: false })
  expect(screen.getByRole('alert')).toHaveTextContent(
    'Only .docx, .pdf, .txt and .md files can be reviewed.',
  )
  await userEvent.upload(input, file('big.pdf', 2 * 1024 * 1024))
  expect(screen.getByRole('alert')).toHaveTextContent('This file is larger than 1 MB.')
  expect(calls.some((c) => c.method === 'POST')).toBe(false)
})

test('upload sends the chosen type and opens the review page', async () => {
  const calls = open()
  await screen.findByText('report.md')
  await userEvent.selectOptions(screen.getByLabelText('Material type'), 'proposal')
  await userEvent.upload(screen.getByLabelText(/choose a file/i), file('new.md'))
  expect(await screen.findByText(/review page/)).toHaveTextContent('/documents/2')
  const post = calls.find((c) => c.method === 'POST')!.body as FormData
  expect(post.get('doc_type')).toBe('proposal')
})

test('server errors are shown with their message', async () => {
  open({
    'POST /documents': () => [
      422,
      { detail: 'This PDF has no text layer (scanned?).', code: 'SCANNED_PDF' },
    ],
  })
  await screen.findByText('report.md')
  await userEvent.upload(screen.getByLabelText(/choose a file/i), file('scan.pdf'))
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'This PDF has no text layer (scanned?).',
  )
})

test('delete asks first', async () => {
  const calls = open({ 'DELETE /documents/1': () => [204, null] })
  await screen.findByText('report.md')
  vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
  await userEvent.click(screen.getByRole('button', { name: 'Delete report.md' }))
  expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
  await userEvent.click(screen.getByRole('button', { name: 'Delete report.md' }))
  await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
})
