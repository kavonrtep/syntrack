import { test, expect, type Page } from '@playwright/test'

/**
 * SCM-ID export flows, driven through the real app against the example pea
 * dataset.
 *
 * These assert behaviour (download fires, TSV is well-formed and complete),
 * not pixels. The server-side half — /highlight?limit=0 completeness and the
 * presence matrix — is covered by tests/api/test_highlight.py and by the unit
 * tests for presenceFromHighlight; what only a browser can check is that the
 * button is reachable, enabled at the right time, and actually produces a file.
 */

/** Wait until genomes have loaded and the track canvas has had time to draw. */
async function waitForViewerReady(page: Page) {
  await expect(page.locator('p.loading')).toHaveCount(0, { timeout: 60_000 })
  await expect(page.locator('aside.sidebar')).toBeVisible()
  await expect(page.locator('.badge')).toHaveCount(0, { timeout: 30_000 })
  await page.waitForTimeout(750)
}

/** Highlight a region by typing it, which needs no canvas geometry (the
 *  header input added in 0.4.0; Ctrl-drag is the mouse equivalent). */
async function highlightByTyping(page: Page) {
  const seq = await page.locator('.region-ctl input[type="text"]').first()
  await seq.fill('chr1:1-5,000,000')
  await page.getByRole('button', { name: 'Highlight' }).click()
  // The status bar reports the highlight once /api/highlight resolves.
  await expect(page.locator('footer .status')).toContainText('highlight', {
    timeout: 60_000,
  })
}

test('top-right SCM IDs button downloads a complete presence TSV', async ({ page }) => {
  await page.goto('/')
  await waitForViewerReady(page)

  const button = page.locator('header').getByRole('button', { name: /SCM IDs/ })
  // Disabled until something is highlighted — there is nothing to export.
  await expect(button).toBeDisabled()

  await highlightByTyping(page)
  await expect(button).toBeEnabled()

  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 120_000 }),
    button.click(),
  ])

  expect(download.suggestedFilename()).toMatch(/^syntrack_.*_scm_ids\.tsv$/)
  const stream = await download.createReadStream()
  const text = await new Promise<string>((resolve, reject) => {
    let out = ''
    stream.on('data', (c: Buffer) => (out += c.toString()))
    stream.on('end', () => resolve(out))
    stream.on('error', reject)
  })

  const lines = text.trimEnd().split('\n')
  const header = lines[0].split('\t')
  expect(header[0]).toBe('scm_id')
  expect(header[1]).toBe('present_in')
  // One 0/1 column per loaded genome.
  expect(header.length).toBeGreaterThan(2)
  expect(lines.length).toBeGreaterThan(1)

  for (const line of lines.slice(1, 50)) {
    const cells = line.split('\t')
    expect(cells).toHaveLength(header.length)
    const presentIn = Number(cells[1])
    const flags = cells.slice(2)
    expect(flags.every((f) => f === '0' || f === '1')).toBe(true)
    // present_in must equal the number of 1s in the row.
    expect(flags.filter((f) => f === '1')).toHaveLength(presentIn)
    expect(presentIn).toBeGreaterThan(0)
  }

  // The export must be complete, not the capped on-screen set: the status bar
  // reports the source SCM count, and every one of them must be a row.
  const status = (await page.locator('footer .status').textContent()) ?? ''
  const reported = Number(/(\d[\d,]*) source SCMs/.exec(status)?.[1]?.replace(/,/g, ''))
  expect(lines.length - 1).toBe(reported)
})

test('marker-set rows show the full name on hover', async ({ page }) => {
  await page.goto('/')
  await waitForViewerReady(page)

  await highlightByTyping(page)
  // Turn the highlight into a marker set, whose auto label is long enough to
  // be truncated in the sidebar (region plus genome id).
  await page.getByRole('button', { name: /Save as set/ }).click()

  const row = page.locator('aside .fish-toggle .toggle-label').first()
  await expect(row).toBeVisible({ timeout: 60_000 })

  const label = (await row.textContent())?.trim() ?? ''
  const tooltip = (await row.getAttribute('title')) ?? ''
  expect(label.length).toBeGreaterThan(0)
  // The tooltip carries the complete name (the row itself is ellipsised) plus
  // the set's size on a second line.
  expect(tooltip.startsWith(label)).toBe(true)
  expect(tooltip).toMatch(/\n[\d,]+ SCMs? · present in \d+ of \d+ genomes?/)
})
