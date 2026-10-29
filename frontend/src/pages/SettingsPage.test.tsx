import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import type { AppSettings } from '../api/client'
import { mockApi, renderAt } from '../test/util'
import SettingsPage from './SettingsPage'

afterEach(() => vi.unstubAllGlobals())

const saved = (over: Partial<AppSettings> = {}): AppSettings => ({
  llm_provider: 'openai_compatible',
  llm_base_url: 'https://api.deepseek.com',
  llm_model: 'deepseek-chat',
  vision_provider: null,
  vision_base_url: '',
  vision_model: '',
  embedding_provider: 'openai_compatible',
  embedding_base_url: '',
  embedding_model: 'text-embedding-v3',
  llm_api_key_set: true,
  llm_api_key_hint: 'a1b2',
  vision_api_key_set: false,
  vision_api_key_hint: '',
  embedding_api_key_set: false,
  embedding_api_key_hint: '',
  default_urls: { groq: 'https://api.groq.com/openai/v1' },
  ...over,
})

function open(routes = {}) {
  const calls = mockApi({
    'GET /settings': () => saved(),
    'PUT /settings': (b) => saved(b as Partial<AppSettings>),
    'GET /health': () => ({ status: 'ok', llm_configured: true }),
    'POST /settings/test': () => ({ ok: true }),
    ...routes,
  })
  renderAt('/settings', <Route path="/settings" element={<SettingsPage />} />)
  return calls
}

const lastPut = (calls: ReturnType<typeof mockApi>) =>
  calls.filter((c) => c.method === 'PUT').slice(-1)[0]?.body as Record<string, unknown>

test('shows saved values but never the key itself', async () => {
  open()
  expect(await screen.findByDisplayValue('deepseek-chat')).toBeInTheDocument()
  const key = screen.getByLabelText('API key', { selector: '#llm-key' })
  expect(key).toHaveValue('')
  expect(key).toHaveAttribute('type', 'password')
  expect(screen.getByText(/Saved key ending in a1b2/)).toBeInTheDocument()
})

test('saving without typing a key keeps the saved key', async () => {
  const calls = open()
  const model = await screen.findByDisplayValue('deepseek-chat')
  await userEvent.clear(model)
  await userEvent.type(model, 'deepseek-reasoner')
  await userEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  await screen.findByText('Settings saved.')
  const body = lastPut(calls)
  expect(body.llm_model).toBe('deepseek-reasoner')
  expect(body).not.toHaveProperty('llm_api_key')
})

test('a typed key is sent once and the field is cleared', async () => {
  const calls = open()
  const key = await screen.findByLabelText('API key', { selector: '#llm-key' })
  await userEvent.type(key, 'sk-new')
  await userEvent.click(screen.getByRole('button', { name: 'Save settings' }))
  await waitFor(() => expect(lastPut(calls).llm_api_key).toBe('sk-new'))
  await waitFor(() => expect(key).toHaveValue(''))
})

test('remove key sends an empty key', async () => {
  const calls = open()
  await userEvent.click(
    await screen.findByRole('button', { name: 'Remove the saved language model key' }),
  )
  await waitFor(() => expect(lastPut(calls)).toEqual({ llm_api_key: '' }))
})

test('a preset fills provider, address and model', async () => {
  open()
  await screen.findByDisplayValue('deepseek-chat')
  await userEvent.selectOptions(screen.getByLabelText('Start from'), 'Groq')
  expect(screen.getByLabelText('Provider', { selector: '#llm-provider' })).toHaveValue('groq')
  expect(screen.getByLabelText('Model', { selector: '#llm-model' })).toHaveValue(
    'llama-3.3-70b-versatile',
  )
})

test('test connection saves first, then reports success', async () => {
  const calls = open()
  await screen.findByDisplayValue('deepseek-chat')
  await userEvent.click(screen.getAllByRole('button', { name: 'Test connection' })[0])
  expect(await screen.findByText('Connected.')).toBeInTheDocument()
  const order = calls.filter((c) => c.method !== 'GET').map((c) => `${c.method} ${c.path}`)
  expect(order).toEqual(['PUT /settings', 'POST /settings/test'])
  expect(calls[calls.length - 1]?.body).toEqual({ target: 'llm' })
})

test('a failed connection shows the provider error', async () => {
  open({
    'POST /settings/test': () => [
      502,
      { detail: 'The connection failed: 401 invalid api key', code: 'TEST_FAILED' },
    ],
  })
  await screen.findByDisplayValue('deepseek-chat')
  await userEvent.click(screen.getAllByRole('button', { name: 'Test connection' })[0])
  expect(await screen.findByRole('alert')).toHaveTextContent('401 invalid api key')
})
