import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // Retry once even locally: mock-mode specs share one vite dev server and a
  // system browser, so the first cold visit occasionally exceeds the timeout.
  // A retry runs against an already-warm server and reliably passes.
  retries: 1,
  // Single worker: these mock-mode specs share one vite dev server, and running
  // them in parallel causes page-load contention (flaky "element not found").
  // The suite is small and fast, so serial execution is the stable choice.
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  // Generous timeouts: with a system browser (channel) + vite on-demand
  // compilation of large components on first visit, the default 5s assertion
  // window is too tight and produces false failures even when the page loads.
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    navigationTimeout: 30_000,
    actionTimeout: 15_000,
  },
  // PW_CHANNEL lets local runs use a system-installed browser (msedge/chrome)
  // instead of Playwright's downloaded chromium — handy when the bundled
  // browser download is blocked by the network. Defaults to system Edge
  // locally (always present on Windows) and falls back to bundled chromium
  // when PW_CHANNEL is explicitly emptied (e.g. on a Linux CI runner).
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        channel: process.env.PW_CHANNEL ?? 'msedge',
      },
    },
  ],
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 5173',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
