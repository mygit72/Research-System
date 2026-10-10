import { defineConfig } from '@playwright/test'

/**
 * Browser test of a public site with the shared free model (FREE_TIER): its own API, started
 * with that configuration, and its own preview of the production build.
 *
 *   npx playwright test -c playwright.free.config.ts
 *
 * The "hosted model" is a stand-in the spec starts on UPSTREAM_PORT; nothing leaves this machine.
 */
const python =
  process.env.E2E_PYTHON ?? (process.platform === 'win32' ? '../backend/.venv/Scripts/python.exe' : 'python')
const API_PORT = 8011
const WEB_PORT = 4174
export const UPSTREAM_PORT = 8012
export const SITE_KEY = 'sk-or-v1-e2e-the-sites-own-key'
export const FREE_MODEL = 'nvidia/nemotron-3-ultra-550b-a55b:free'
export const DOWNLOAD_URL = 'https://example.org/research-intelligence.zip'

export default defineConfig({
  testDir: 'e2e/free',
  timeout: 120_000,
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    channel: process.env.CI ? undefined : 'chrome',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `"${python}" ../backend/scripts/e2e_server.py`,
      url: `http://127.0.0.1:${API_PORT}/health`,
      env: {
        E2E_API_PORT: String(API_PORT),
        E2E_ENV: JSON.stringify({
          LLM_PROVIDER: 'openai',
          LLM_API_BASE: `http://127.0.0.1:${UPSTREAM_PORT}/v1`,
          OPENAI_API_KEY: SITE_KEY,
          LLM_MODEL: FREE_MODEL,
          FREE_TIER: 'true',
          FREE_TIER_LABEL: 'Nemotron 3 Ultra (free)',
          FREE_TIER_HOST: 'NVIDIA, through OpenRouter',
          FREE_TIER_DAILY_REQUESTS_PER_USER: '2',
          FREE_TIER_REQUESTS_PER_MINUTE: '0',
          ALLOW_LOCAL_MODELS: 'false', // as on a public server
          DOWNLOAD_URL,
        }),
      },
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: `npm run build && npx vite preview --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      env: { VITE_API_PROXY: `http://127.0.0.1:${API_PORT}` },
      timeout: 240_000,
      reuseExistingServer: false,
    },
  ],
})
