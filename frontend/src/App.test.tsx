import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { Shell } from './App'
import { setLang } from './strings'
import { mockApi, renderAt } from './test/util'

afterEach(() => {
  vi.unstubAllGlobals()
  setLang('en')
})

const open = (path = '/', health: object = { status: 'ok', llm_configured: true }) => {
  mockApi({ 'GET /health': () => health })
  renderAt(path, <Route path="*" element={<Shell />} />)
}

test('nav shows the three main sections', () => {
  open()
  for (const name of ['Documents', 'Knowledge base', 'Prompts']) {
    expect(screen.getByRole('link', { name })).toBeInTheDocument()
  }
})

test('unknown route shows not found', () => {
  open('/nope')
  expect(screen.getByText(/page not found/i)).toBeInTheDocument()
})

test('banner when the language model is not configured', async () => {
  open('/nope', { status: 'ok', llm_configured: false })
  expect(await screen.findByRole('status')).toHaveTextContent(/No language model is set up/)
})

test('language toggle switches the interface to Chinese', async () => {
  open('/nope')
  await userEvent.click(screen.getByRole('button', { name: '中文' }))
  expect(screen.getByRole('link', { name: '学生材料' })).toBeInTheDocument()
})
