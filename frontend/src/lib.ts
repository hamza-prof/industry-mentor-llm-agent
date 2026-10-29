import { useQuery } from '@tanstack/react-query'
import { api, type ReviewComment } from './api/client'

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: api.health, staleTime: 30_000 })
}

export function formatDate(iso: string, lang: string) {
  return new Date(iso).toLocaleDateString(lang === 'zh' ? 'zh-CN' : 'en-GB', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export interface Filter {
  category: string
  severity: string
  status: string
  origin: string
  hideRejected: boolean
}

export const NO_FILTER: Filter = {
  category: '',
  severity: '',
  status: '',
  origin: '',
  hideRejected: false,
}

export function applyFilter(cs: ReviewComment[], f: Filter): ReviewComment[] {
  return cs.filter(
    (c) =>
      (!f.category || c.category === f.category) &&
      (!f.severity || c.severity === f.severity) &&
      (!f.status || c.status === f.status) &&
      (!f.origin || c.origin === f.origin) &&
      !(f.hideRejected && c.status === 'rejected'),
  )
}
