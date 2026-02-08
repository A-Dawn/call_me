import { defineConfig, devices } from '@playwright/test'

// Avoid proxy interference when probing local webServer availability on Windows.
const localNoProxy = '127.0.0.1,localhost'
if (!process.env.NO_PROXY) {
  process.env.NO_PROXY = localNoProxy
} else if (!process.env.NO_PROXY.includes('127.0.0.1')) {
  process.env.NO_PROXY = `${process.env.NO_PROXY},${localNoProxy}`
}
process.env.no_proxy = process.env.NO_PROXY

export default defineConfig({
  testDir: '../../test/call_me/frontend/tests-e2e',
  timeout: 30_000,
  expect: {
    timeout: 20_000,
  },
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'bun ../../test/call_me/frontend/scripts/e2e-webserver.mjs',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
