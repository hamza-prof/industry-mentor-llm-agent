import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import type { Prompt } from '../api/client'
import { mockApi, renderAt } from '../test/util'
import PromptsPage from './PromptsPage'

afterEach(() => vi.unstubAllGlobals())

const prompt = (over: Partial<Prompt> = {}): Prompt => ({
  key: 'overall_feedback',
  description: 'One overall feedback paragraph.',
  required: ['comments'],
  optional: ['doc_type', 'language', 'summary'],
  active_version: 1,
  system: 'You are a mentor.',
  user: 'Write feedback.\n{summary}\n{comments}',
  ...over,
})

function open(routes = {}) {
  const calls = mockApi({
    'GET /prompts': () => [
      prompt(),
      prompt({ key: 'section_review', required: ['section'], user: '{section}' }),
    ],
    'GET /prompts/overall_feedback/versions': () => [
      { version: 1, system: 's', user: 'u', created_at: '2026-10-28T10:00:00' },
    ],
    'PUT /prompts/overall_feedback': (b) => ({ ...prompt(), ...(b as object), active_version: 2 }),
    'POST /prompts/overall_feedback/reset': () => ({ ...prompt(), active_version: 3 }),
    ...routes, // last: a test's routes replace the defaults
  })
  renderAt('/prompts', <Route path="/prompts" element={<PromptsPage />} />)
  return calls
}

test('placeholder chips show which required ones are present', async () => {
  open()
  const chip = await screen.findByText('{comments}')
  expect(chip).toHaveAttribute('data-present', 'true')
  const user = screen.getByLabelText('Task')
  await userEvent.clear(user)
  await userEvent.type(user, 'Write feedback.')
  expect(screen.getByText('{comments}')).toHaveAttribute('data-present', 'false')
  expect(screen.getByText('Missing required placeholder: {comments}')).toBeInTheDocument()
})

test('save shows the new version', async () => {
  const calls = open()
  await screen.findByText('{comments}')
  await userEvent.type(screen.getByLabelText('Role and rules'), ' Be kind.')
  await userEvent.click(screen.getByRole('button', { name: 'Save as new version' }))
  expect(await screen.findByText('Saved as version 2.')).toBeInTheDocument()
  expect(calls.find((c) => c.method === 'PUT')?.body).toMatchObject({
    system: 'You are a mentor. Be kind.',
  })
})

test('server validation errors are shown inline', async () => {
  open({
    'PUT /prompts/overall_feedback': () => [
      422,
      {
        detail: 'Prompt is invalid.',
        code: 'PROMPT_INVALID',
        missing: [],
        unknown: ['foo'],
        errors: [],
      },
    ],
  })
  await screen.findByText('{comments}')
  await userEvent.click(screen.getByRole('button', { name: 'Save as new version' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Unknown placeholder: {foo}')
})

test('reset asks for confirmation', async () => {
  const calls = open()
  await screen.findByText('{comments}')
  vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
  await userEvent.click(screen.getByRole('button', { name: 'Reset to default' }))
  expect(calls.some((c) => c.path.endsWith('/reset'))).toBe(false)
  await userEvent.click(screen.getByRole('button', { name: 'Reset to default' }))
  await waitFor(() => expect(calls.some((c) => c.path.endsWith('/reset'))).toBe(true))
})

test('choosing another prompt opens it', async () => {
  open()
  await userEvent.click(await screen.findByRole('button', { name: /Section review/ }))
  expect(screen.getByText('{section}', { selector: '[data-present]' })).toBeInTheDocument()
})
