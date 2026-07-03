import { test, expect } from '@playwright/test'
import path from 'node:path'

// Phase-2 E2E: the insight surface. Drives the BUILT app served by the running
// FastAPI backend at http://localhost:8001/app/ (see playwright.config.ts). It
// exercises the REAL Phase-2 features end-to-end against the real agent:
//   - the auto-profile card + clickable follow-up chips on upload
//   - sending a follow-up chip and getting a real answer
//   - the "📊 Chart" toggle + a grouped question rendering a real chart with
//     PNG/SVG download buttons
//   - the per-answer cost badge and the header "Today: $x" running total
//   - the Export menu with CSV/Parquet/Code/Report items
// These are content assertions against real LLM output, not 200 checks.

const CSV_FIXTURE = path.join(__dirname, 'fixtures', 'sales.csv')

test('auto-profile + follow-up chips render and a chip sends a real question', async ({ page }) => {
  await page.goto('/app/')

  await page.getByTestId('file-input').setInputFiles(CSV_FIXTURE)

  // The richer profile card appears with the real schema.
  const profileCard = page.getByTestId('profile-card')
  await expect(profileCard).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('schema-table')).toContainText('revenue')
  await expect(page.getByTestId('schema-table')).toContainText('region')

  // At least two real, clickable follow-up chips are suggested.
  const chips = page.getByTestId('followup-chip')
  await expect(chips.first()).toBeVisible({ timeout: 30_000 })
  expect(await chips.count()).toBeGreaterThanOrEqual(2)

  // Clicking a chip sends a question and a real answer arrives.
  await chips.first().click()
  await expect(page.getByTestId('user-message').last()).toBeVisible()
  const agent = page.getByTestId('agent-message').last()
  await expect(agent).toHaveAttribute('data-status', 'completed', { timeout: 120_000 })
  const answer = agent.getByTestId('answer-text')
  await expect(answer).not.toBeEmpty()

  // The per-answer cost badge shows a real $ value...
  const costBadge = agent.getByTestId('cost-badge')
  await expect(costBadge).toBeVisible()
  await expect(costBadge).toContainText('$')

  // ...and the header running total shows a $ value.
  const today = page.getByTestId('today-cost')
  await expect(today).toContainText('$')

  // The Export menu opens and lists all four export kinds.
  await agent.getByTestId('export-menu').click()
  await expect(agent.getByTestId('export-csv')).toBeVisible()
  await expect(agent.getByTestId('export-parquet')).toBeVisible()
  await expect(agent.getByTestId('export-code')).toBeVisible()
  await expect(agent.getByTestId('export-report')).toBeVisible()

  // Each export item points at the run-scoped export endpoint.
  const csvHref = await agent.getByTestId('export-csv').getAttribute('href')
  expect(csvHref).toContain('/analyses/')
  expect(csvHref).toContain('kind=csv')
})

test('the Chart toggle + a grouped question renders a downloadable chart', async ({ page }) => {
  await page.goto('/app/')

  await page.getByTestId('file-input').setInputFiles(CSV_FIXTURE)
  await expect(page.getByTestId('profile-card')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('composer-input')).toBeEnabled()

  // Turn on the (now real) Chart toggle.
  const toggle = page.getByTestId('chart-toggle')
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-pressed', 'true')

  // Ask a grouped question that warrants a chart.
  await page.getByTestId('composer-input').fill('Show me total revenue by region')
  await page.getByTestId('send-button').click()

  const agent = page.getByTestId('agent-message').last()
  await expect(agent).toHaveAttribute('data-status', 'completed', { timeout: 120_000 })

  // A real chart renders with a vega-drawn SVG/canvas inside it.
  const chart = agent.getByTestId('chart')
  await expect(chart).toBeVisible({ timeout: 30_000 })
  await expect(chart.locator('svg, canvas').first()).toBeVisible({ timeout: 30_000 })

  // The PNG/SVG download buttons exist.
  await expect(agent.getByTestId('chart-download-png')).toBeVisible()
  await expect(agent.getByTestId('chart-download-svg')).toBeVisible()
})

test('the coming-soon rail is retired for a real Sources panel', async ({ page }) => {
  await page.goto('/app/')

  // Phase 3: the "Coming soon" rail is gone; a real multi-source panel replaces it.
  await expect(page.getByTestId('coming-soon-rail')).toHaveCount(0)
  const panel = page.getByTestId('source-panel')
  await expect(panel).toBeVisible()
  await expect(panel).toContainText('Sources')

  // No now-real features remain as rail stubs.
  await expect(page.getByTestId('rail-connect-db')).toHaveCount(0)
  await expect(page.getByTestId('rail-multi-source')).toHaveCount(0)
  await expect(page.getByTestId('rail-sessions')).toHaveCount(0)
  await expect(page.getByTestId('rail-formats')).toHaveCount(0)

  // The header "Today:" total is real (not a disabled stub).
  const today = page.getByTestId('today-cost')
  await expect(today).not.toHaveAttribute('aria-disabled', 'true')
  await expect(today).toContainText('Today:')
})
