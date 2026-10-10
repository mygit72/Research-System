import { createServer, type Server } from 'node:http'
import { fileURLToPath } from 'node:url'
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { DOWNLOAD_URL, FREE_MODEL, SITE_KEY, UPSTREAM_PORT } from '../../playwright.free.config'

/**
 * A public site with the shared free model: nothing is sent to it until the user turns it on;
 * then answers come from it through the site's key, up to the daily allowance.
 *
 * The hosted model is a stand-in started here (OpenAI's streaming format, a fixed answer).
 */
const PAPER = fileURLToPath(new URL('../fixtures/low-rank-adapters.pdf', import.meta.url))
const TITLE = 'Low-Rank Adapters for Efficient Domain Adaptation of Language Models'
const ANSWER = 'The free model says low-rank adapters cut memory [1].'

let upstream: Server
const calls: { authorization?: string; model: string; body: string }[] = []

test.beforeAll(async () => {
  upstream = createServer((request, response) => {
    let body = ''
    request.on('data', (chunk) => (body += chunk))
    request.on('end', () => {
      calls.push({ authorization: request.headers.authorization, model: JSON.parse(body).model, body })
      response.setHeader('Content-Type', 'text/event-stream')
      const chunks = [
        { choices: [{ delta: { content: ANSWER } }] },
        { choices: [{ delta: {}, finish_reason: 'stop' }], usage: { prompt_tokens: 100, completion_tokens: 12 } },
      ]
      response.end(chunks.map((c) => `data: ${JSON.stringify(c)}\n\n`).join('') + 'data: [DONE]\n\n')
    })
  })
  await new Promise<void>((resolve) => upstream.listen(UPSTREAM_PORT, '127.0.0.1', resolve))
})

test.afterAll(() => upstream?.close())

async function audit(page: Page, label: string) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  return results.violations.map((v) => `${label}: ${v.id} — ${v.help}\n    ${v.nodes.slice(0, 4).map((n) => n.target.join(' ')).join('\n    ')}`)
}

async function askInChat(page: Page, question: string) {
  await page.getByPlaceholder(/ask a question/i).fill(question)
  await page.keyboard.press('Enter')
}

test('the free shared model is used only once chosen, and up to the daily allowance', async ({ page }) => {
  const problems: string[] = []
  page.on('pageerror', (error) => problems.push(String(error)))
  page.on('console', (message) => {
    if (message.type() === 'error' && !/401/.test(message.text())) problems.push(message.text())
  })
  const email = `free-${Date.now()}@example.com`

  await page.goto('/register')
  await page.getByLabel('Name').fill('Free Rider')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('end-to-end-2026')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.getByRole('button', { name: 'Skip' }).click()

  // 1. Uploading sends nothing to the model's host, and no model is in effect yet.
  await page.goto('/papers')
  await page.getByRole('button', { name: 'Upload papers' }).click()
  await page.getByLabel('Choose files to upload').setInputFiles(PAPER)
  await expect(page.getByText('Uploaded — processing has started.')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByText('Ready').first()).toBeVisible({ timeout: 60_000 })
  await page.getByText(TITLE).first().click()
  await expect(async () => {
    await page.reload()
    await expect(page.getByText('Searchable')).toBeVisible({ timeout: 2_000 })
  }).toPass({ timeout: 120_000 })
  await page.goto('/chat')
  await expect(page.getByText(/Choose how to run the AI features first/)).toBeVisible()
  expect(calls).toEqual([])

  // 2. Settings says what the free model costs (speed, allowance, where it runs) before the choice.
  await page.goto('/settings')
  await expect(page.getByText('Not chosen yet')).toBeVisible()
  await expect(page.getByRole('radio', { name: /Free shared model/ })).toHaveAttribute('aria-checked', 'true')
  await expect(page.getByText(/Free, and slower/)).toBeVisible()
  await expect(page.getByText(/2 of 2 requests left today/)).toBeVisible()
  await expect(page.getByText(/It runs at NVIDIA, through OpenRouter, not on this site/)).toBeVisible()
  // Privacy → who can see your work: nobody else, with the two limits of a hosted site said plainly.
  await expect(page.getByText(/Nothing you add is public/)).toBeVisible()
  await expect(page.getByText(/whoever runs the server can technically reach/)).toBeVisible()
  await expect(page.getByText(/None chosen yet, so nothing is sent to any model/)).toBeVisible()
  const violations: string[] = []
  for (const scheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
    await page.getByRole('radio', { name: /Free shared model/ }).click()
    await page.waitForTimeout(300)
    violations.push(...(await audit(page, `${scheme} free model`)))
    // A public server can't reach a model on your computer: that tab explains your own copy.
    await page.getByRole('radio', { name: /Run it on my computer/ }).click()
    await expect(page.getByRole('link', { name: /Download the app/ })).toHaveAttribute('href', DOWNLOAD_URL)
    await page.waitForTimeout(300)
    violations.push(...(await audit(page, `${scheme} own copy`)))
  }
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 390, height: 800 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.setViewportSize({ width: 1280, height: 720 })

  await page.getByRole('radio', { name: /Free shared model/ }).click()
  await page.getByRole('button', { name: 'Use the free model' }).click()
  await expect(page.getByText('Your AI work now runs on the free shared model.')).toBeVisible()
  await expect(page.getByText('In use')).toBeVisible()
  await expect(page.getByText(new RegExp(`${FREE_MODEL.replace(/[.]/g, '\\.')} · free shared model at NVIDIA`))).toBeVisible()
  expect(await page.content()).not.toContain(SITE_KEY)

  // 3. Answers come from it, through the site's key, with nothing that names the user.
  await page.goto('/chat')
  await askInChat(page, 'How much GPU memory do low-rank adapters save?')
  await expect(page.getByText('The free model says low-rank adapters cut memory')).toBeVisible({ timeout: 60_000 })
  expect(calls).toHaveLength(1)
  expect(calls[0].authorization).toBe(`Bearer ${SITE_KEY}`)
  expect(calls[0].model).toBe(FREE_MODEL)
  expect(calls[0].body).not.toContain(email)
  expect(calls[0].body).not.toContain('Free Rider')

  // 4. The allowance (2 a day here): the third question is refused, and not sent.
  await askInChat(page, 'And how many parameters do the adapters train?')
  await expect(page.getByText('The free model says low-rank adapters cut memory')).toHaveCount(2, { timeout: 60_000 })
  await askInChat(page, 'What about the training time of adapters?')
  await expect(page.getByText(/You've used today's 2 free requests/).first()).toBeVisible({ timeout: 60_000 })
  expect(calls).toHaveLength(2)
  await page.goto('/settings')
  await expect(page.getByText(/0 of 2 requests left today/)).toBeVisible()

  // 5. Turning it off again: no model is in effect.
  await page.getByRole('button', { name: 'Stop using it' }).click()
  await expect(page.getByText('Not chosen yet')).toBeVisible()

  expect(violations, violations.join('\n')).toEqual([])
  expect(problems, problems.join('\n')).toEqual([])
})
