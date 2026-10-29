import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Routes } from 'react-router-dom'
import { vi } from 'vitest'

type Handler = (body: unknown, init: RequestInit) => [number, unknown] | unknown
export type Calls = { method: string; path: string; body: unknown }[]

/** Stub fetch with "METHOD /path" → handler (returns body, or [status, body]). Logs every call. */
export function mockApi(routes: Record<string, Handler>): Calls {
  const calls: Calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      const path = url.replace(/^\/api/, '')
      let body: unknown = init.body
      if (typeof body === 'string') body = JSON.parse(body)
      calls.push({ method, path, body })
      const key = Object.keys(routes).find((k) => {
        const [m, p] = k.split(' ')
        return m === method && new RegExp(`^${p.replace(/\?/g, '\\?')}$`).test(path)
      })
      if (!key)
        return new Response(JSON.stringify({ detail: 'no mock', code: 'NO_MOCK' }), { status: 500 })
      const out = await routes[key](body, init)
      const [status, data] = Array.isArray(out) && typeof out[0] === 'number' ? out : [200, out]
      return status === 204
        ? new Response(null, { status })
        : new Response(JSON.stringify(data), { status })
    }),
  )
  return calls
}

export function renderAt(path: string, routes: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>{routes}</Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
