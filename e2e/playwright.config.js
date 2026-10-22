import { defineConfig } from '@playwright/test'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.js',
  workers: 1,
  fullyParallel: false,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: 'list',
  outputDir: '../test-results',
  use: {
    baseURL: 'http://127.0.0.1:8081',
    trace: 'retain-on-failure',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } : {},
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 1000 } } },
    { name: 'mobile', use: { viewport: { width: 360, height: 800 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: `${resolve(import.meta.dirname, '../backend/.venv/bin/python')} -m regresslab.cli demo --port 8081`,
    url: 'http://127.0.0.1:8081/api/demo/health',
    reuseExistingServer: false,
    timeout: 20_000,
    env: { REGRESSLAB_DATA_DIR: mkdtempSync(join(tmpdir(), 'regresslab-e2e-')) },
  },
})
