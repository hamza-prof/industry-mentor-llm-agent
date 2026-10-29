import { defineConfig } from '@playwright/test'

// Smoke tests against the real app with LLM_PROVIDER=fake: deterministic and free.
// Own ports and a throwaway data folder, so a running dev setup is left alone.
const API = 'http://127.0.0.1:8001'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  use: { baseURL: 'http://127.0.0.1:5174', locale: 'en-US' },
  webServer: [
    {
      command:
        'cd ../backend && rm -rf .e2e-data && LLM_PROVIDER=fake DATA_DIR=.e2e-data VISION_MODEL= ' +
        'EMBEDDING_BASE_URL= EMBEDDING_API_KEY= .venv/bin/uvicorn app.main:app --port 8001',
      url: `${API}/api/health`,
      reuseExistingServer: false,
    },
    {
      command: 'npx vite --port 5174 --strictPort',
      env: { API_URL: API },
      url: 'http://127.0.0.1:5174',
      reuseExistingServer: false,
    },
  ],
})
