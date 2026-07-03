import { test, expect } from '@playwright/test'
import path from 'node:path'

// Phase-4 E2E: the LOCAL Data workbench. Drives the BUILT app served by the
// running FastAPI backend at http://localhost:8001/app/ (see playwright.config.ts).
// It exercises the REAL Phase-4 endpoints end-to-end against the real backend —
// no LLM call is on this path, everything runs locally:
//   - upload two related CSVs (customers.id unique; orders.customer_id -> it)
//   - open the Data panel and assert the profile tiles render with the right row
//     count plus a PK badge and an FK badge
//   - click a column tile -> the value-counts drill-in appears
//   - run a valid SELECT ... FROM data -> the result table + row count render
//   - run a broken query -> a friendly inline error (no crash / stack trace)
//   - the Download CSV button is present and triggers a download
//   - the three Phase-5 stubs are visibly labelled "Coming soon"
// These are content assertions against real local computation, not 200 checks.

const CUSTOMERS = path.join(__dirname, 'fixtures', 'customers.csv')
const ORDERS = path.join(__dirname, 'fixtures', 'orders.csv')

test('data workbench: tiles, drill-in, SQL query, download, and labelled stubs', async ({
  page,
}) => {
  await page.goto('/app/')

  // Upload the parent (customers, unique id) then the child (orders, customer_id).
  await page.getByTestId('file-input').setInputFiles(CUSTOMERS)
  await expect(page.getByTestId('profile-message').filter({ hasText: 'customers.csv' })).toBeVisible(
    { timeout: 30_000 },
  )

  await page.getByTestId('file-input').setInputFiles(ORDERS)
  await expect(page.getByTestId('profile-message').filter({ hasText: 'orders.csv' })).toBeVisible({
    timeout: 30_000,
  })

  // The Data tab is now enabled; open the workbench (defaults to the newest file:
  // orders.csv).
  const dataTab = page.getByTestId('tab-data')
  await expect(dataTab).toBeEnabled()
  await dataTab.click()

  const workbench = page.getByTestId('workbench')
  await expect(workbench).toBeVisible()

  // Profile tiles render with the correct full-data row count (orders has 10 rows).
  await expect(page.getByTestId('profile-tiles')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('tile-row-count-value')).toHaveText('10')

  // A PK badge (order_id is unique + non-null) and an FK badge (customer_id ->
  // customers.id) render.
  await expect(page.getByTestId('pk-badge').first()).toBeVisible()
  const fkBadge = page.getByTestId('fk-badge').first()
  await expect(fkBadge).toBeVisible()
  await expect(fkBadge).toContainText('FK')
  await expect(fkBadge).toContainText('customers')

  // Clicking a column tile opens the value-counts drill-in with real counts.
  await page.getByTestId('column-tile').filter({ hasText: 'customer_id' }).click()
  const drill = page.getByTestId('column-values')
  await expect(drill).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('column-value-row').first()).toBeVisible()

  // Run a valid grouped SELECT over the `data` view.
  await page.getByTestId('sql-input').fill('SELECT customer_id, COUNT(*) AS n FROM data GROUP BY customer_id ORDER BY n DESC')
  await page.getByTestId('run-query').click()

  const resultTable = page.getByTestId('result-table')
  await expect(resultTable).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('result-grid')).toBeVisible()
  await expect(page.getByTestId('result-row-count')).toBeVisible()
  // Six distinct customer_ids in the fixture (1,2,3,4,5,6).
  await expect(page.getByTestId('result-row-count')).toHaveText('6')

  // The Download CSV button is present and triggers a real file download.
  const downloadBtn = page.getByTestId('download-csv')
  await expect(downloadBtn).toBeVisible()
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    downloadBtn.click(),
  ])
  expect(download.suggestedFilename()).toContain('.csv')

  // A broken query shows a friendly inline error — no crash, no stack trace.
  await page.getByTestId('sql-input').fill('SELECT * FROM nope')
  await page.getByTestId('run-query').click()
  const sqlError = page.getByTestId('sql-error')
  await expect(sqlError).toBeVisible({ timeout: 30_000 })
  await expect(sqlError).not.toContainText('Traceback')
  // The workbench is still usable (the box did not crash).
  await expect(page.getByTestId('sql-input')).toBeEnabled()

  // The three Phase-5 stubs are present and visibly labelled "Coming soon".
  const dashboardStub = page.getByTestId('stub-dashboard')
  await expect(dashboardStub).toBeVisible()
  await expect(dashboardStub).toContainText('Coming soon')

  const chart3dStub = page.getByTestId('stub-chart3d')
  await expect(chart3dStub).toBeVisible()
  await expect(chart3dStub).toContainText('Coming soon')

  const connectStub = page.getByTestId('stub-connect-create-table')
  await expect(connectStub).toBeVisible()
  await expect(connectStub).toContainText('Coming soon')

  // The cloud "connect & create table" stub makes NO live call — its form preview
  // carries the explicit cloud-egress warning.
  await connectStub.click()
  await expect(page.getByTestId('stub-cloud-warning')).toContainText('cloud')
})
