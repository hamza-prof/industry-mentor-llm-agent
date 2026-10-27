import { NavLink, Route, Routes } from 'react-router-dom'

const sections = [
  { to: '/', label: 'Documents' },
  { to: '/kb', label: 'Knowledge Base' },
  { to: '/prompts', label: 'Prompts' },
]

function Placeholder({ title }: { title: string }) {
  return <h1 className="text-xl font-semibold">{title}</h1>
}

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <nav className="flex gap-6 border-b bg-white px-6 py-3">
        <span className="font-bold">Mentor Review Assistant</span>
        {sections.map((s) => (
          <NavLink
            key={s.to}
            to={s.to}
            end
            className={({ isActive }) =>
              isActive ? 'font-semibold text-blue-600' : 'text-slate-600'
            }
          >
            {s.label}
          </NavLink>
        ))}
      </nav>
      <main className="p-6">
        <Routes>
          <Route path="/" element={<Placeholder title="Documents" />} />
          <Route path="/kb" element={<Placeholder title="Knowledge Base" />} />
          <Route path="/prompts" element={<Placeholder title="Prompts" />} />
          <Route path="*" element={<Placeholder title="Page not found" />} />
        </Routes>
      </main>
    </div>
  )
}
