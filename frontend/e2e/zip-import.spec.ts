import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { crc32 } from 'node:zlib'

/** A valid zip (stored, no compression) made from {name: text}; enough for the import dialog. */
function makeZip(files: Record<string, string>): Buffer {
  const parts: Buffer[] = []
  const central: Buffer[] = []
  let offset = 0
  for (const [name, text] of Object.entries(files)) {
    const data = Buffer.from(text)
    const nameBytes = Buffer.from(name)
    const crc = crc32(data)
    const local = Buffer.alloc(30)
    local.writeUInt32LE(0x04034b50, 0)
    local.writeUInt16LE(20, 4)
    local.writeUInt32LE(crc, 14)
    local.writeUInt32LE(data.length, 18)
    local.writeUInt32LE(data.length, 22)
    local.writeUInt16LE(nameBytes.length, 26)
    const header = Buffer.alloc(46)
    header.writeUInt32LE(0x02014b50, 0)
    header.writeUInt16LE(20, 4)
    header.writeUInt16LE(20, 6)
    header.writeUInt32LE(crc, 16)
    header.writeUInt32LE(data.length, 20)
    header.writeUInt32LE(data.length, 24)
    header.writeUInt16LE(nameBytes.length, 28)
    header.writeUInt32LE(offset, 42)
    parts.push(local, nameBytes, data)
    central.push(header, nameBytes)
    offset += 30 + nameBytes.length + data.length
  }
  const directory = Buffer.concat(central)
  const end = Buffer.alloc(22)
  end.writeUInt32LE(0x06054b50, 0)
  end.writeUInt16LE(Object.keys(files).length, 8)
  end.writeUInt16LE(Object.keys(files).length, 10)
  end.writeUInt32LE(directory.length, 12)
  end.writeUInt32LE(offset, 16)
  return Buffer.concat([...parts, directory, end])
}

const NOTE = (title: string) =>
  `# ${title}\n\nAbstract\n\nThis note studies ${title.toLowerCase()} for scientific question answering. ` +
  'We compare retrieval methods on a benchmark and report recall and exact match.\n\n## Introduction\n\n' +
  'Retrieval-augmented systems answer questions from papers. '.repeat(8)

test('a zip of papers becomes a library and a collection, and says what it left out', async ({ page }) => {
  const errors: string[] = []
  page.on('console', (m) => m.type() === 'error' && !/status of 4\d\d/.test(m.text()) && errors.push(m.text()))
  page.on('pageerror', (e) => errors.push(e.message))

  await page.goto('/register')
  await page.getByLabel('Name').fill('Zip Importer')
  await page.getByLabel('Email').fill(`zip-${Date.now()}@example.com`)
  await page.getByLabel('Password').fill('zip-import-2026')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page).toHaveURL(/\/$/)
  await page.getByRole('button', { name: 'Skip' }).click()

  await page.goto('/papers')
  await page.getByRole('button', { name: 'Import zip' }).click()
  const dialog = page.getByRole('dialog', { name: 'Import a zip of papers' })
  await expect(dialog.getByRole('button', { name: 'Import', exact: true })).toBeDisabled()

  await dialog.getByLabel('Zip file').setInputFiles({
    name: 'thesis.zip',
    mimeType: 'application/zip',
    buffer: makeZip({
      'thesis/dense-retrieval.md': NOTE('Dense retrieval'),
      'thesis/adapters.md': NOTE('Low-rank adapters'),
      'thesis/figure.png': 'not really a png',
      'thesis/.DS_Store': 'junk',
    }),
  })
  await dialog.getByLabel('Put the papers in a new collection').fill('Thesis reading')
  await dialog.getByRole('button', { name: 'Import', exact: true }).click()

  await expect(dialog.getByRole('status')).toContainText('2 papers imported')
  await expect(dialog.getByText('1 file skipped')).toBeVisible()
  await dialog.getByText('1 file skipped').click()
  await expect(dialog).toContainText('figure.png')
  await expect(dialog).toContainText('Not a supported file type')
  await expect(dialog).not.toContainText('.DS_Store') // litter isn't worth reporting

  for (const scheme of ['light', 'dark'] as const) {
    // Reduced motion: no fades, so axe measures final colours, not a frame of an animation.
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(results.violations.map((v) => `${scheme}: ${v.id} — ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)).toEqual([])
  }

  // The collection exists and holds both papers.
  await dialog.getByRole('link', { name: 'Open the new collection' }).click()
  await expect(page.getByRole('heading', { name: 'Thesis reading' })).toBeVisible()
  await expect(page.getByText('Dense retrieval').first()).toBeVisible()
  await expect(page.getByText('Low-rank adapters').first()).toBeVisible()

  // A project can now be started from it.
  await page.goto('/projects')
  await expect(page.getByRole('combobox').first()).toContainText('Thesis reading (2)')

  // A file that isn't a zip is refused with a reason, and the dialog stays usable.
  await page.goto('/papers')
  await page.getByRole('button', { name: 'Import zip' }).click()
  const again = page.getByRole('dialog', { name: 'Import a zip of papers' })
  await again.getByLabel('Zip file').setInputFiles({ name: 'fake.zip', mimeType: 'application/zip', buffer: Buffer.from('nope') })
  await again.getByRole('button', { name: 'Import', exact: true }).click()
  await expect(again.getByRole('alert')).toContainText('valid zip')
  await expect(again.getByLabel('Zip file')).toBeVisible()

  expect(errors).toEqual([])
})
