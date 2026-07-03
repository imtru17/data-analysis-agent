import { defineConfig, devices } from '@playwright/test'

// E2E config for the Phase-1 smoke test. It drives the BUILT static export served
// by the FastAPI backend at http://localhost:8001/app/. The backend (built by the
// parallel slice) must already be running — the qa-auditor boots it:
//   uv run alembic upgrade head && (cd frontend && pnpm build) && uv run python -m src
// then: cd frontend && pnpm exec playwright test
//
// Override the target with E2E_BASE_URL if serving elsewhere.

const baseURL = process.env.E2E_BASE_URL ?? 'http://localhost:8001/app/'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
