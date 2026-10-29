import { NavLink, Route, Routes } from 'react-router-dom'
import { ApiError, NETWORK_ERROR } from './api/client'
import { useHealth } from './lib'
import DocumentsPage from './pages/DocumentsPage'
import KnowledgeBasePage from './pages/KnowledgeBasePage'
import PromptsPage from './pages/PromptsPage'
import ReviewPage from './pages/ReviewPage'
import { setLang, useLang, useT } from './strings'

export function Shell() {
  const t = useT()
  const lang = useLang()
  const health = useHealth()
  const offline = health.error instanceof ApiError && health.error.code === NETWORK_ERROR
  const banner = offline
    ? t.offline
    : health.data && !health.data.llm_configured
      ? t.llmMissing
      : null
  const links = [
    { to: '/', label: t.nav.documents },
    { to: '/kb', label: t.nav.kb },
    { to: '/prompts', label: t.nav.prompts },
  ]
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">{t.appName}</span>
        <nav className="flex gap-1">
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.to === '/'} className="navlink">
              {l.label}
            </NavLink>
          ))}
        </nav>
        <button className="lang" onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}>
          {t.langToggle}
        </button>
      </header>
      {banner && (
        <p role="status" className="banner">
          {banner}
        </p>
      )}
      <Routes>
        <Route path="/" element={<DocumentsPage />} />
        <Route path="/documents/:id" element={<ReviewPage />} />
        <Route path="/kb" element={<KnowledgeBasePage />} />
        <Route path="/prompts" element={<PromptsPage />} />
        <Route path="*" element={<p className="page-msg">{t.notFound}</p>} />
      </Routes>
    </div>
  )
}

export default Shell
