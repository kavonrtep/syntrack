import { test, expect } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

/**
 * Screenshot smoke flows. Each test drives the real app to a key state and
 * saves a PNG into ./screenshots for direct inspection. These are NOT
 * pixel-diff assertions (the canvas is data-dependent and the dataset can
 * change) — they assert the app reaches a sane DOM state, then capture the
 * pixels so a human / agent can eyeball the render.
 */

const SHOTS = join(dirname(fileURLToPath(import.meta.url)), 'screenshots')

/** Wait until genomes have loaded and the track canvas has had time to draw. */
async function waitForViewerReady(page: import('@playwright/test').Page) {
  // The "Loading genomes…" paragraph is replaced by the sidebar once
  // SCMStore data arrives over /api/genomes.
  await expect(page.locator('p.loading')).toHaveCount(0, { timeout: 60_000 })
  await expect(page.locator('aside.sidebar')).toBeVisible()
  // Canvas draw happens in a post-load $effect; the transient "loading…" badge
  // clears when the first frame is painted.
  await expect(page.locator('.badge')).toHaveCount(0, { timeout: 30_000 })
  // Small settle for the ribbon/overlay layers to finish their first frame.
  await page.waitForTimeout(750)
}

test('initial viewer render', async ({ page }) => {
  await page.goto('/')
  await waitForViewerReady(page)

  // Sanity: the meta line reports a non-zero genome + SCM count.
  await expect(page.locator('header .meta')).toContainText('genomes')

  await page.screenshot({ path: join(SHOTS, '01-initial.png'), fullPage: false })
  await page
    .locator('.canvas-container')
    .screenshot({ path: join(SHOTS, '02-canvas.png') })
})

test('recolor by a non-default reference genome', async ({ page }) => {
  await page.goto('/')
  await waitForViewerReady(page)

  // "Color by:" select — pick the last option (a specific genome, not the
  // "(top genome)" default) to exercise the per-genome palette path.
  const select = page.locator('header .ref-ctl select')
  const optionCount = await select.locator('option').count()
  expect(optionCount).toBeGreaterThan(1)
  await select.selectOption({ index: optionCount - 1 })
  // Recoloring re-fetches connections; wait for the "loading…" badge to clear
  // so it doesn't bleed into the shot, then a short settle for the redraw.
  await expect(page.locator('.badge')).toHaveCount(0, { timeout: 30_000 })
  await page.waitForTimeout(500)

  await page.screenshot({ path: join(SHOTS, '03-recolor.png'), fullPage: false })
})

test('FISH preview toggle (if marker sets present)', async ({ page }) => {
  await page.goto('/')
  await waitForViewerReady(page)

  const fishBtn = page.getByRole('button', { name: 'FISH preview' })
  // The button is disabled when no marker sets are loaded — the example
  // dataset ships none, so this flow is best-effort and skips cleanly.
  if (await fishBtn.isDisabled()) {
    test.skip(true, 'no marker sets loaded in the example dataset')
  }
  await fishBtn.click()
  await expect(page.getByText('FISH density')).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.badge')).toHaveCount(0, { timeout: 30_000 })
  await page.waitForTimeout(500)

  await page.screenshot({ path: join(SHOTS, '04-fish-preview.png'), fullPage: false })
})
