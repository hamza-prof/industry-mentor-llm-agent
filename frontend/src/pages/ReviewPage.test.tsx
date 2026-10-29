import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { Review } from '../api/client'
import { comment, doc, review } from '../test/fixtures'
import { mockApi, renderAt } from '../test/util'
import ReviewPage from './ReviewPage'

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn()
})
afterEach(() => vi.unstubAllGlobals())

function open(r: Review | null = review(), extra = {}) {
  const calls = mockApi({
    ...extra, // first: a test's own routes win over the defaults below
    'GET /documents/1': () => doc,
    'GET /documents/1/reviews': () => (r ? [{ ...r, comments: null }] : []),
    'GET /reviews/10': () => r,
    'PATCH /comments/\\d+': (body) => ({ ...comment({}), ...(body as object) }),
  })
  renderAt('/documents/1', <Route path="/documents/:id" element={<ReviewPage />} />)
  return calls
}

const card = (el: HTMLElement) => el.closest('article') as HTMLElement

test('shows summary, document and margin notes', async () => {
  open()
  expect(await screen.findByText('Slow deploys of the order system.')).toBeInTheDocument()
  expect(screen.getByText('We moved the order system to microservices.')).toBeInTheDocument()
  expect(screen.getByText('Happier is not measured.')).toBeInTheDocument()
  expect(screen.getAllByText('Not found in the document')).toHaveLength(2)
})

test('clicking a note scrolls to and highlights its paragraph', async () => {
  open()
  await userEvent.click(await screen.findByText('Why microservices?'))
  const para = document.getElementById('p-S1.P1')!
  expect(para.scrollIntoView).toHaveBeenCalled()
  expect(para).toHaveAttribute('data-active', 'true')
})

test('the active note quote is marked inside the paragraph', async () => {
  open()
  await userEvent.click(await screen.findByText('Happier is not measured.'))
  const mark = document.querySelector('#p-S2\\.P1 mark')
  expect(mark).toHaveTextContent('much happier')
})

test('accept updates at once and sends PATCH', async () => {
  let release!: () => void
  const pending = new Promise<void>((r) => (release = r))
  const calls = open(review(), {
    'PATCH /comments/1': async () => {
      await pending
      return comment({ id: 1, status: 'accepted' })
    },
  })
  const c = card(await screen.findByText('Happier is not measured.'))
  await userEvent.click(within(c).getByRole('button', { name: 'Accept' }))
  expect(await within(c).findByLabelText('Confirmed')).toBeInTheDocument() // seal shows while PATCH is held
  expect(calls.find((x) => x.method === 'PATCH')).toMatchObject({
    path: '/comments/1',
    body: { status: 'accepted' },
  })
  await act(async () => release())
})

test('a failed accept is rolled back with the server message', async () => {
  open(review(), { 'PATCH /comments/1': () => [500, { detail: 'Database is locked.', code: 'X' }] })
  const c = card(await screen.findByText('Happier is not measured.'))
  await userEvent.click(within(c).getByRole('button', { name: 'Accept' }))
  expect(await screen.findByText('Database is locked.')).toBeInTheDocument()
  expect(within(c).queryByLabelText('Confirmed')).not.toBeInTheDocument()
})

test('editing requires text', async () => {
  const calls = open()
  const c = card(await screen.findByText('Happier is not measured.'))
  await userEvent.click(within(c).getByRole('button', { name: 'Edit' }))
  const box = within(c).getByRole('textbox')
  await userEvent.clear(box)
  await userEvent.click(within(c).getByRole('button', { name: 'Save' }))
  expect(within(c).getByText('Write the note before saving it.')).toBeInTheDocument()
  expect(calls.some((x) => x.method === 'PATCH')).toBe(false)
  await userEvent.type(box, 'Report the survey score.')
  await userEvent.click(within(c).getByRole('button', { name: 'Save' }))
  expect(calls.find((x) => x.method === 'PATCH')?.body).toEqual({
    status: 'edited',
    mentor_text: 'Report the survey score.',
  })
})

test('rejected notes are hidden by the filter', async () => {
  open()
  expect(await screen.findByText('Rejected idea.')).toBeInTheDocument()
  await userEvent.click(screen.getByLabelText('Hide rejected'))
  expect(screen.queryByText('Rejected idea.')).not.toBeInTheDocument()
})

test('severity filter narrows the list', async () => {
  open()
  await screen.findByText('Happier is not measured.')
  await userEvent.selectOptions(screen.getByLabelText('Severity'), 'medium')
  expect(screen.getByText('Why microservices?')).toBeInTheDocument()
  expect(screen.queryByText('Happier is not measured.')).not.toBeInTheDocument()
})

test('document-level notes are listed under Whole document', async () => {
  open()
  const general = (await screen.findByRole('heading', { name: 'Whole document' })).closest(
    'section',
  )!
  expect(within(general).getByText('No references section.')).toBeInTheDocument()
})

test('figures render as images with the caption as alt text, and their notes jump to them', async () => {
  open()
  const img = await screen.findByAltText('Figure 1 Deploy time')
  expect(img).toHaveAttribute('src', `/api/documents/1/figures/${'a'.repeat(32)}`)
  await userEvent.click(await screen.findByText('Axis has no unit.'))
  expect(document.getElementById('p-S2.P2')!.scrollIntoView).toHaveBeenCalled()
})

test('opening a figure shows what the assistant saw', async () => {
  open()
  await userEvent.click(await screen.findByRole('button', { name: /Figure 1 Deploy time/ }))
  expect(screen.getByText('Bar chart of deploy minutes')).toBeInTheDocument()
  expect(screen.getByText('after: 6')).toBeInTheDocument()
})

test('a partial review offers a retry', async () => {
  const calls = open(
    review({ status: 'partial', errors: [{ section_id: 'S2', error: 'timeout' }] }),
    {
      'POST /reviews/10/retry': () => review({ status: 'queued' }),
    },
  )
  await userEvent.click(await screen.findByRole('button', { name: 'Retry the failed sections' }))
  expect(calls.some((x) => x.method === 'POST' && x.path === '/reviews/10/retry')).toBe(true)
})

test('no review yet offers to start one', async () => {
  const calls = open(null, { 'POST /reviews': () => review({ status: 'queued' }) })
  await userEvent.click(await screen.findByRole('button', { name: 'Start review' }))
  expect(calls.find((x) => x.method === 'POST')?.body).toEqual({ document_id: 1 })
})

test('running review shows its progress', async () => {
  open(review({ status: 'running', stage: 'sections 2/5', comments: [] }))
  expect(await screen.findByRole('progressbar')).toHaveAttribute('aria-valuenow', '40')
  expect(screen.getByText(/Reviewing sections/)).toBeInTheDocument()
})

test('keyboard: j selects the next note and a accepts it', async () => {
  const calls = open()
  await screen.findByText('Happier is not measured.')
  fireEvent.keyDown(document.body, { key: 'j' })
  fireEvent.keyDown(document.body, { key: 'a' })
  await waitFor(() => expect(calls.some((x) => x.method === 'PATCH')).toBe(true))
  expect(calls.find((x) => x.method === 'PATCH')).toMatchObject({
    path: '/comments/2',
    body: { status: 'accepted' },
  })
})

test('accept all shown uses the bulk endpoint for the visible pending notes', async () => {
  const calls = open(review(), { 'POST /reviews/10/comments/bulk': () => [] })
  await screen.findByText('Happier is not measured.')
  await userEvent.selectOptions(screen.getByLabelText('Severity'), 'high')
  await userEvent.click(screen.getByRole('button', { name: 'Accept all shown' }))
  expect(calls.find((x) => x.path.endsWith('/bulk'))?.body).toEqual({
    ids: [1],
    status: 'accepted',
  })
})

test('selecting text in a paragraph lets the mentor add a note on it', async () => {
  const calls = open(review(), {
    'POST /reviews/10/comments': () => [
      201,
      comment({ id: 9, origin: 'mentor', status: 'accepted', problem: 'Which users?' }),
    ],
  })
  const para = (await screen.findByText('Users are much happier now.')).closest(
    '[data-pid]',
  ) as HTMLElement
  const range = document.createRange()
  range.setStart(para.querySelector('span')!.firstChild!, 0)
  range.setEnd(para.querySelector('span')!.firstChild!, 5)
  window.getSelection()!.removeAllRanges()
  window.getSelection()!.addRange(range)
  fireEvent.mouseUp(para)
  await userEvent.click(screen.getByRole('button', { name: 'Add a note on the selected text' }))
  await userEvent.type(screen.getByLabelText('Note'), 'Which users?')
  await userEvent.click(screen.getByRole('button', { name: 'Add note' }))
  expect(calls.find((x) => x.method === 'POST')?.body).toMatchObject({
    paragraph_id: 'S2.P1',
    quote: 'Users',
    problem: 'Which users?',
  })
})

test('overall feedback can be drafted and the exports are links', async () => {
  const calls = open(review(), {
    'POST /reviews/10/overall': () =>
      review({ overall_feedback: 'Clear structure; add evidence.' }),
  })
  await userEvent.click(await screen.findByRole('button', { name: 'Draft from confirmed notes' }))
  expect(await screen.findByDisplayValue('Clear structure; add evidence.')).toBeInTheDocument()
  expect(calls.some((x) => x.path === '/reviews/10/overall')).toBe(true)
  expect(screen.getByRole('link', { name: 'Download Word' })).toHaveAttribute(
    'href',
    '/api/reviews/10/export?format=docx',
  )
})
