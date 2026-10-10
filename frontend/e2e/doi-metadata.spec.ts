import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

/**
 * "Fill from DOI" in the paper's details dialog, and the import dialog's DOI handling. The test API
 * has no internet, so this covers what a browser can prove here: the button's state, that a value
 * that isn't a DOI is refused with a reason, a DOI that isn't on arXiv is explained, and
 * accessibility. The Crossref lookup itself is covered by the backend tests.
 */
test('the DOI actions explain themselves and are accessible', async ({ page }) => {
  const errors: string[] = []
  // The browser logs every 4xx response; this test provokes some on purpose (and the page-load
  // session refresh answers 401), so only other errors count.
  page.on('console', (m) => m.type() === 'error' && !/status of 4\d\d/.test(m.text()) && errors.push(m.text()))
  page.on('pageerror', (e) => errors.push(e.message))

  await page.goto('/register')
  await page.getByLabel('Name').fill('Doi Checker')
  await page.getByLabel('Email').fill(`doi-${Date.now()}@example.com`)
  await page.getByLabel('Password').fill('doi-lookup-2026')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.getByRole('button', { name: 'Skip' }).click()
  await page.getByRole('button', { name: 'Try sample papers' }).click()
  await expect(page.getByText(/sample papers added/)).toBeVisible()

  // Import dialog: text that is neither an arXiv id nor a DOI is refused, with a hint.
  await page.goto('/papers')
  await page.getByRole('button', { name: /Import from arXiv/ }).click()
  const dialog = page.getByRole('dialog', { name: 'Import from arXiv' })
  await expect(dialog).toContainText('arXiv DOIs')
  await dialog.getByRole('textbox', { name: 'arXiv ids, links or DOIs' }).fill('what is this')
  await dialog.getByRole('button', { name: /^Import/ }).click()
  await expect(dialog.getByRole('alert')).toContainText(/isn.t an arXiv id, arXiv link or DOI/)
  await page.keyboard.press('Escape')

  // Paper details: Fill from DOI needs a DOI, and a malformed one is refused with a reason.
  await page.getByRole('link', { name: /Low-Rank Adapters/ }).first().click()
  await page.getByRole('button', { name: 'More actions' }).click()
  await page.getByRole('menuitem', { name: 'Edit details' }).click()
  const edit = page.getByRole('dialog', { name: 'Edit paper details' })
  const fill = edit.getByRole('button', { name: 'Fill from DOI' })
  await expect(fill).toBeDisabled()
  await edit.getByLabel('DOI').fill('not-a-doi')
  await expect(fill).toBeEnabled()
  await fill.click()
  await expect(edit.getByRole('alert')).toContainText(/isn.t a DOI/)

  for (const scheme of ['light', 'dark'] as const) {
    await page.emulateMedia({ colorScheme: scheme })
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(results.violations.map((v) => `${scheme}: ${v.id} — ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
  }
  expect(errors).toEqual([])
})
