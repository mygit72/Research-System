import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

/**
 * The Research Project Builder's guidance: a new project shows what to do next and a detailed
 * guide for the step, and the starter code can be read, copied and downloaded.
 */
test('a project explains each step and hands over runnable starter code', async ({ page }) => {
  const errors: string[] = []
  page.on('console', (m) => m.type() === 'error' && !m.text().includes('401') && errors.push(m.text()))
  // (the session refresh at page load answers 401 before anyone is signed in; that is expected)
  page.on('pageerror', (e) => errors.push(e.message))

  await page.goto('/register')
  await page.getByLabel('Name').fill('Guide Walker')
  await page.getByLabel('Email').fill(`guide-${Date.now()}@example.com`)
  await page.getByLabel('Password').fill('guided-walk-2026')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.getByRole('button', { name: 'Skip' }).click()

  // Start a project from an idea.
  await page.goto('/projects')
  await page.getByRole('textbox', { name: 'Your idea' }).fill('Adapt a retriever with low-rank adapters')
  await page.getByRole('button', { name: /Start project/ }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+/)

  // What to do next, and why a library matters.
  const guidance = page.getByRole('region', { name: 'Guidance' })
  await expect(guidance).toContainText('Next:')
  await expect(guidance).toContainText('research question')
  await expect(guidance).toContainText('Link a collection')

  // The step guide: why, numbered actions, what to expect, checks, mistakes, this project.
  const guide = page.getByRole('region', { name: 'Step guide' })
  await expect(guide.getByRole('button', { name: /How this step works · step 1 of 7/ })).toHaveAttribute('aria-expanded', 'true')
  await expect(guide).toContainText('Why this step')
  await expect(guide.getByRole('listitem').filter({ hasText: 'Write your idea in plain words' })).toBeVisible()
  await expect(guide).toContainText('What you should end up with')
  await expect(guide).toContainText('Common mistakes')
  await expect(guide).toContainText('Your project right now')
  await expect(guide).toContainText('Adapt a retriever with low-rank adapters')

  // Collapsing hides it; every step has its own guide.
  await guide.getByRole('button', { name: /How this step works/ }).click()
  await expect(guide).not.toContainText('Why this step')
  await guide.getByRole('button', { name: /How this step works/ }).click()
  for (const [label, step] of [
    ['Background', 'step 2 of 7'],
    ['Gap & hypothesis', 'step 3 of 7'],
    ['Methods', 'step 4 of 7'],
    ['Experiments', 'step 5 of 7'],
    ['Paper outline', 'step 6 of 7'],
  ] as const) {
    await page.getByRole('navigation', { name: 'Project steps' }).getByRole('button', { name: new RegExp(label) }).click()
    await expect(guide.getByRole('button', { name: new RegExp(step) })).toBeVisible()
    await expect(guide).toContainText('What to do')
  }

  // Starter code: files with purposes, the walkthrough, copy, download.
  await page.getByRole('navigation', { name: 'Project steps' }).getByRole('button', { name: /Starter code/ }).click()
  await expect(guide.getByRole('button', { name: /step 7 of 7/ })).toBeVisible()
  const files = page.getByRole('list', { name: 'Files' })
  for (const name of ['README.md', 'config.json', 'systems.py', 'metrics.py', 'data.py', 'run_experiments.py', 'test_pipeline.py']) {
    await expect(files).toContainText(name)
  }
  await expect(page.getByLabel('Contents of README.md')).toContainText('Step by step')
  await expect(page.getByLabel('Contents of README.md')).toContainText('python run_experiments.py --smoke')
  await files.getByRole('button', { name: /systems\.py/ }).click()
  await expect(page.getByLabel('Contents of systems.py')).toContainText('class YourApproach')
  await expect(page.getByLabel('Contents of systems.py')).toContainText('NotImplementedError')

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: /Download \.zip/ }).click(),
  ])
  expect(download.suggestedFilename()).toMatch(/starter-code\.zip$/)
  const bytes = readFileSync((await download.path()) as string)
  expect(bytes.subarray(0, 2).toString()).toBe('PK')

  // No automatically detectable accessibility problems on the new views.
  for (const scheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: scheme })
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(
      results.violations.map((v) => `${scheme}: ${v.id} — ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`),
    ).toEqual([])
  }

  // Phone width: nothing wider than the screen.
  await page.setViewportSize({ width: 390, height: 800 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)

  expect(errors).toEqual([])
})
