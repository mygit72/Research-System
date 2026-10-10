import { createServer, type Server } from 'node:http'
import type { AddressInfo } from 'node:net'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

/**
 * Settings → AI: a user picks their own model, and their answers come from it.
 *
 * By default the "local model" is a stand-in Ollama started here (it lists two models and
 * answers every chat with a fixed sentence), so the run is deterministic. With
 * E2E_REAL_OLLAMA=1 the same steps run against the Ollama on this machine (qwen2.5:3b).
 */
const PAPER = fileURLToPath(new URL('./fixtures/low-rank-adapters.pdf', import.meta.url))
const TITLE = 'Low-Rank Adapters for Efficient Domain Adaptation of Language Models'
const REAL = Boolean(process.env.E2E_REAL_OLLAMA)
const KEY = 'gsk_e2e_secret_key_value_9876'
const STAND_IN_ANSWER = 'The stand-in model says low-rank adapters cut memory [1].'

let standIn: Server
let ollamaUrl = 'http://127.0.0.1:11434'
const chats: { model: string }[] = []

test.beforeAll(async () => {
  if (REAL) return
  standIn = createServer((request, response) => {
    let body = ''
    request.on('data', (chunk) => (body += chunk))
    request.on('end', () => {
      response.setHeader('Content-Type', 'application/json')
      if (request.method === 'GET' && request.url === '/api/tags') {
        response.end(JSON.stringify({ models: [{ name: 'stand-in:7b' }, { name: 'tiny:1b' }] }))
      } else if (request.method === 'POST' && request.url === '/api/chat') {
        chats.push({ model: JSON.parse(body).model })
        response.end(
          JSON.stringify({
            model: 'stand-in:7b',
            message: { role: 'assistant', content: STAND_IN_ANSWER },
            done: true,
            done_reason: 'stop',
            prompt_eval_count: 100,
            eval_count: 12,
          }) + '\n',
        )
      } else {
        response.statusCode = 404
        response.end('{}')
      }
    })
  })
  await new Promise<void>((resolve) => standIn.listen(0, '127.0.0.1', resolve))
  ollamaUrl = `http://127.0.0.1:${(standIn.address() as AddressInfo).port}`
})

test.afterAll(() => standIn?.close())

test('choose your own model in Settings and get answers from it', async ({ page }) => {
  test.setTimeout(REAL ? 300_000 : 120_000)
  const problems: string[] = []
  page.on('pageerror', (error) => problems.push(String(error)))
  page.on('console', (message) => {
    if (message.type() === 'error' && !/401/.test(message.text())) problems.push(message.text())
  })

  await page.goto('/register')
  await page.getByLabel('Name').fill('Model Chooser')
  await page.getByLabel('Email').fill(`models-${Date.now()}@example.com`)
  await page.getByLabel('Password').fill('end-to-end-2026')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.getByRole('button', { name: 'Skip' }).click()

  // 1. An API key: saved, then shown only as its last four characters.
  await page.goto('/settings')
  await page.getByRole('radio', { name: /My own API key/ }).click()
  await page.getByLabel('Provider').selectOption('groq')
  await expect(page.getByRole('link', { name: /Get a key/ })).toHaveAttribute('href', 'https://console.groq.com/keys')
  await page.getByLabel('Groq API key').fill(KEY)
  await page.getByLabel('Model', { exact: true }).fill('llama-3.3-70b-versatile')
  await page.getByRole('button', { name: 'Use this model' }).click()
  await expect(page.getByText(/Your AI work now runs on llama-3.3-70b-versatile/)).toBeVisible()
  await expect(page.getByText(/your key …9876/)).toBeVisible() // the AI summary row
  await page.reload()
  await expect(page.getByPlaceholder(/Saved key …9876/)).toHaveValue('')
  expect(await page.content()).not.toContain(KEY)

  // 2. A model on this computer: test the connection, pick from the list, save.
  await page.getByRole('radio', { name: /A model on my computer/ }).click()
  await page.getByLabel('Provider').selectOption('ollama')
  await page.getByLabel('Address').fill(ollamaUrl)
  await page.getByRole('button', { name: 'Test connection' }).click()
  await expect(page.getByRole('status').filter({ hasText: /Connected: \d+ model/ })).toBeVisible()
  const model = REAL ? 'qwen2.5:3b' : 'stand-in:7b'
  await page.getByLabel('Model', { exact: true }).fill(model)
  await page.getByRole('button', { name: 'Use this model' }).click()
  await expect(page.getByText(new RegExp(`Your AI work now runs on ${model.replace('.', '\\.')}`))).toBeVisible()
  await expect(page.getByText(new RegExp(`${model.replace('.', '\\.')} · Ollama .*local \\(your choice\\)`))).toBeVisible()

  // 3. Answers now come from that model.
  await page.goto('/papers')
  await page.getByRole('button', { name: 'Upload papers' }).click()
  await page.getByLabel('Choose files to upload').setInputFiles(PAPER)
  await expect(page.getByText('Uploaded — processing has started.')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByText('Ready').first()).toBeVisible({ timeout: 60_000 })
  // "Ready" means parsed; searching needs the index too (slower while a local model is loaded).
  await page.getByText(TITLE).first().click()
  await expect(async () => {
    await page.reload()
    await expect(page.getByText('Searchable')).toBeVisible({ timeout: 2_000 })
  }).toPass({ timeout: 120_000 })
  await page.goto('/chat')
  await page.getByPlaceholder(/ask a question/i).fill('How much GPU memory do low-rank adapters save?')
  await page.keyboard.press('Enter')
  const citation = page.getByRole('button', { name: new RegExp(`^Source \\d+: ${TITLE}`) }).first()
  await expect(citation).toBeVisible({ timeout: REAL ? 240_000 : 60_000 })
  if (!REAL) {
    await expect(page.getByText('The stand-in model says low-rank adapters cut memory')).toBeVisible()
    expect(chats.map((c) => c.model)).toEqual(['stand-in:7b'])
  }

  // 4. Back to the server's model: the saved choice (and key) are gone.
  await page.goto('/settings')
  await page.getByRole('radio', { name: /This server's model/ }).click()
  await page.getByRole('button', { name: "Use this server's model" }).click()
  await expect(page.getByText('In use')).toBeVisible()

  expect(problems, problems.join('\n')).toEqual([])
})
