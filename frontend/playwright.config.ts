import { defineConfig } from '@playwright/test'

/**
 * Browser end-to-end tests: the production build (`vite preview`, with the production
 * Content-Security-Policy) against an API with a fresh database and deterministic models
 * (backend/scripts/e2e_server.py).
 *
 *   npx playwright test           # locally: uses the installed Chrome
 *   CI=1 npx playwright test      # CI: Playwright's Chromium (npx playwright install chromium)
 */
const python =
  process.env.E2E_PYTHON ?? (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : 'python')
const API_PORT = 8010

export default defineConfig({
  testDir: 'e2e',
  testIgnore: 'free/**', // a site with the shared free model: playwright.free.config.ts
  timeout: 120_000,
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: 'http://localhost:4173',
    channel: process.env.CI ? undefined : 'chrome',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `"${python}" ../backend/scripts/e2e_server.py`,
      url: `http://127.0.0.1:${API_PORT}/health`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: 'npm run build && npx vite preview --port 4173 --strictPort',
      url: 'http://localhost:4173',
      env: { VITE_API_PROXY: `http://127.0.0.1:${API_PORT}` },
      timeout: 240_000,
      reuseExistingServer: false,
    },
  ],
})
