import { defineConfig, devices } from '@playwright/test'

/**
 * Screenshot smoke harness (ONBOARDING.md "Browser verification").
 *
 * Closes the visual blind spot that type-check + build + unit tests leave open:
 * none of those render a pixel, so a frozen canvas / wrong FISH colors / blank
 * render slips through. This drives the real production bundle in headless
 * Chromium and saves PNGs at key states for direct inspection.
 *
 * Scope (intentionally lean): chromium headless-shell ONLY — no firefox/webkit.
 * The browser binary lives in ~/.cache/ms-playwright (persistent sandbox home);
 * the shared-library deps come from the container image (v4.1+).
 *
 * webServer builds `dist` then serves it + the example pea dataset through the
 * syntrack FastAPI server (SYNTRACK_FRONTEND_DIR mounts the SPA at /). The
 * server only answers /healthz with 200 once SCMStore.load has finished, so it
 * doubles as the readiness probe.
 */
export default defineConfig({
  testDir: './tests/e2e',
  // One worker: a single shared backend serving the real dataset; parallel
  // pages would just contend on it with no speedup.
  workers: 1,
  fullyParallel: false,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://127.0.0.1:8765',
    // Headless shell is the default in headless mode; pin the channel so we
    // never silently fall back to (or require) the full chromium build.
    channel: 'chromium-headless-shell',
    viewport: { width: 1440, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], channel: 'chromium-headless-shell' },
    },
  ],
  webServer: {
    // cwd defaults to this config's dir (frontend/). Build the bundle, then
    // hop to the repo root and serve it through dev.sh (which neutralizes the
    // hermit PIP_TARGET/PYTHONPATH).
    command:
      'npm run build && cd .. && SYNTRACK_FRONTEND_DIR=frontend/dist ./dev.sh syntrack serve --host 127.0.0.1 --port 8765 --config example_data/syntrack_config.yaml',
    url: 'http://127.0.0.1:8765/healthz',
    // Build + real-pea-dataset load; generous so a cold start doesn't flake.
    timeout: 240_000,
    reuseExistingServer: !process.env.CI,
    stdout: 'pipe',
    stderr: 'pipe',
  },
})
