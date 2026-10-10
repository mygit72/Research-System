import { expect, test } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const PAPER = fileURLToPath(new URL('./fixtures/low-rank-adapters.pdf', import.meta.url))
const TITLE = 'Low-Rank Adapters for Efficient Domain Adaptation of Language Models'

test('upload a paper, ask about it, and check the cited evidence', async ({ page }) => {
  const problems: string[] = []
  page.on('pageerror', (error) => problems.push(String(error)))
  page.on('console', (message) => {
    // Content-Security-Policy violations and script errors (401s while signed out are expected).
    if (message.type() === 'error' && !/401/.test(message.text())) problems.push(message.text())
  })

  // Register.
  await page.goto('/register')
  await page.getByLabel('Name').fill('E2E Researcher')
  await page.getByLabel('Email').fill(`e2e-${Date.now()}@example.com`)
  await page.getByLabel('Password').fill('end-to-end-2026')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.getByRole('button', { name: 'Skip' }).click() // first-run tour

  // Upload, and wait until the paper is processed and indexed.
  await page.goto('/papers')
  await page.getByRole('button', { name: 'Upload papers' }).click()
  await page.getByLabel('Choose files to upload').setInputFiles(PAPER)
  await expect(page.getByText('Uploaded — processing has started.')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByText(TITLE).first()).toBeVisible()
  await expect(page.getByText('Ready').first()).toBeVisible({ timeout: 60_000 })

  // Ask in the research chat.
  await page.goto('/chat')
  await page.getByPlaceholder(/ask a question/i).fill('How much GPU memory do low-rank adapters save?')
  await page.keyboard.press('Enter')

  // The answer cites a passage, is checked, and its sources are the uploaded paper.
  const citation = page.getByRole('button', { name: new RegExp(`^Source \\d+: ${TITLE}`) }).first()
  await expect(citation).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText(/Well supported|Partially supported/).first()).toBeVisible()
  await page.getByRole('button', { name: /View sources/ }).click()
  await expect(page.getByRole('dialog').getByText(TITLE).first()).toBeVisible()
  await expect(page.getByRole('dialog').getByText('Cited in the answer').first()).toBeVisible()

  expect(problems, problems.join('\n')).toEqual([])
})
