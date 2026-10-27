import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { expect, test } from 'vitest'
import App from './App'

test('nav shows the three main sections', () => {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  )
  for (const name of ['Documents', 'Knowledge Base', 'Prompts']) {
    expect(screen.getByRole('link', { name })).toBeInTheDocument()
  }
})

test('unknown route shows not found', () => {
  render(
    <MemoryRouter initialEntries={['/nope']}>
      <App />
    </MemoryRouter>,
  )
  expect(screen.getByText(/page not found/i)).toBeInTheDocument()
})
