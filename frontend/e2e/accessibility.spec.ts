import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

/**
 * Automated accessibility audit (axe-core, WCAG 2.1 A/AA rules) of the main pages, in light
 * and dark themes, with the sample papers loaded so pages show real content.
 * Automated checks find roughly a third of accessibility problems; keyboard and screen-reader
 * walkthroughs cover the rest (see docs/ACCESSIBILITY.md).
 */
const PAGES = [
  '/',
  '/papers',
  '/search?q=low-rank%20adapters',
  '/chat',
  '/collections',
  '/notes',
  '/compare',
  '/reviews',
  '/projects',
  '/graph',
  '/evaluation',
  '/usage',
  '/settings',
  '/help',
]

async function audit(page: Page, label: string) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  return results.violations.map((v) => {
    const nodes = v.nodes.slice(0, 4).map((n) => {
      const data = n.any[0]?.data as { fgColor?: string; bgColor?: string; contrastRatio?: number } | undefined
      const colors = data?.fgColor ? ` [${data.fgColor} on ${data.bgColor}: ${data.contrastRatio}]` : ''
      return `${n.target.join(' ')}${colors}`
    })
    return `${label}: ${v.id} (${v.impact}) — ${v.help}\n    ${nodes.join('\n    ')}`
  })
}

test('main pages have no automatically detectable accessibility violations', async ({ page }) => {
  await page.goto('/register')
  await page.getByLabel('Name').fill('A11y Auditor')
  await page.getByLabel('Email').fill(`a11y-${Date.now()}@example.com`)
  await page.getByLabel('Password').fill('accessible-2026')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.getByRole('button', { name: 'Skip' }).click()
  await page.getByRole('button', { name: 'Try sample papers' }).click()
  await expect(page.getByText(/sample papers added/)).toBeVisible()

  const problems: string[] = []
  for (const scheme of ['light', 'dark'] as const) {
    // Reduced motion: no fades, so axe measures final colours, not a frame of an animation.
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
    for (const path of PAGES) {
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(300) // let skeletons settle
      problems.push(...(await audit(page, `${scheme} ${path}`)))
    }
  }
  // A paper page (reader + tabs).
  await page.goto('/papers')
  await page.getByRole('link', { name: /Low-Rank Adapters/ }).first().click()
  await page.waitForLoadState('networkidle')
  problems.push(...(await audit(page, 'paper page')))

  expect(problems, problems.join('\n')).toEqual([])
})
