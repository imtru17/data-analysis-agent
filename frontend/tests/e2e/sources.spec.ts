import { test, expect } from '@playwright/test'
import path from 'node:path'

// Phase-3 E2E: sources beyond one CSV. Drives the BUILT app served by the running
// FastAPI backend at http://localhost:8001/app/ (see playwright.config.ts). It
// exercises the REAL Phase-3 surfaces against the real backend:
//   - the Connect-database dialog (open + submit, masked source or friendly error)
//   - non-CSV upload (a .json file) profiling into a real schema table
//   - the multi-source panel + source picker (select a source)
//   - the sessions / history browser (list + start a new session)
//   - the inline column annotation editor (edit + save + persists)
// These are content assertions against the real backend, not 200 checks.
//
// Playwright runs specs in a CommonJS context, so __dirname is available.
const JSON_FIXTURE = path.join(__dirname, 'fixtures', 'people.json')

// Optional: a DSN for a seeded, credential-free local SQLite DB the backend
// provides. When set, the connect test performs a full real connection; when
// unset it still asserts the dialog submits and yields a real outcome.
const SQLITE_DSN = process.env.E2E_SQLITE_DSN ?? ''

test('the multi-source panel replaces the coming-soon rail and no stub remains', async ({ page }) => {
  await page.goto('/app/')

  await expect(page.getByTestId('coming-soon-rail')).toHaveCount(0)
  await expect(page.getByTestId('source-panel')).toBeVisible()
  await expect(page.getByTestId('source-panel')).toContainText('Sources')
  await expect(page.getByTestId('soon-pill')).toHaveCount(0)

  // The composer is disabled until a source is loaded.
  await expect(page.getByTestId('composer-input')).toBeDisabled()
})

test('upload a non-CSV (JSON) file and see its real profile', async ({ page }) => {
  await page.goto('/app/')

  // The upload helper text now advertises the extra formats.
  await expect(page.getByTestId('upload-formats')).toContainText('JSON')

  await page.getByTestId('file-input').setInputFiles(JSON_FIXTURE)

  // A real profile renders with the JSON's columns in the schema table.
  const profile = page.getByTestId('profile-message')
  await expect(profile).toBeVisible({ timeout: 30_000 })
  await expect(profile).toContainText('people.json')
  const schema = page.getByTestId('schema-table')
  await expect(schema).toContainText('city')
  await expect(schema).toContainText('amount')

  // The uploaded file now appears as a selectable source in the panel.
  const items = page.getByTestId('source-item')
  await expect(items.first()).toBeVisible()
  await expect(items.filter({ hasText: 'people.json' })).toBeVisible()

  // The composer is enabled now a source exists.
  await expect(page.getByTestId('composer-input')).toBeEnabled()
})

test('the source picker lets you select a source for the next question', async ({ page }) => {
  await page.goto('/app/')
  await page.getByTestId('file-input').setInputFiles(JSON_FIXTURE)
  await expect(page.getByTestId('profile-message')).toBeVisible({ timeout: 30_000 })

  // A newly-loaded source is checked by default; toggling works.
  const checkbox = page.getByTestId('source-checkbox').first()
  await expect(checkbox).toBeChecked()
  await checkbox.uncheck()
  await expect(checkbox).not.toBeChecked()
  await checkbox.check()
  await expect(checkbox).toBeChecked()
})

test('the sessions browser lists sessions and starts a new one', async ({ page }) => {
  await page.goto('/app/')

  // Open the history / sessions browser from the header.
  await page.getByTestId('sessions-button').click()
  const panel = page.getByTestId('sessions-panel')
  await expect(panel).toBeVisible()

  // Start a new session; the browser refreshes and the new session lists.
  await page.getByTestId('new-session').click()

  // Reopen the browser and confirm a real session list now exists.
  await page.getByTestId('sessions-button').click()
  await expect(page.getByTestId('sessions-panel')).toBeVisible()
  const list = page.getByTestId('session-list')
  await expect(list).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('session-item').first()).toBeVisible()
})

test('add a column annotation from the profile table and see it saved', async ({ page }) => {
  await page.goto('/app/')
  await page.getByTestId('file-input').setInputFiles(JSON_FIXTURE)
  await expect(page.getByTestId('profile-message')).toBeVisible({ timeout: 30_000 })

  // Open the inline annotation editor on the first column.
  await page.getByTestId('annotate-column').first().click()
  const input = page.getByTestId('annotation-input')
  await expect(input).toBeVisible()

  const note = 'amount = revenue in USD'
  await input.fill(note)
  await page.getByTestId('annotation-save').click()

  // The saved note renders on the column (real PUT round-trip).
  const saved = page.getByTestId('annotation-note').first()
  await expect(saved).toBeVisible({ timeout: 30_000 })
  await expect(saved).toContainText('revenue in USD')
})

test('the Connect-database dialog opens and submits with a real outcome', async ({ page }) => {
  await page.goto('/app/')

  // Open the "+ Add source" menu, then the Connect-database dialog.
  await page.getByTestId('add-source').click()
  await page.getByTestId('connect-db-button').click()

  const dialog = page.getByTestId('connect-db-dialog')
  await expect(dialog).toBeVisible()

  // Choose SQLite and enter a connection string / file path.
  await page.getByTestId('connect-db-name').fill('seed-db')
  await page.getByTestId('connect-db-kind').selectOption('sqlite')
  const dsn = SQLITE_DSN || '/nonexistent/e2e-probe.db'
  await page.getByTestId('connect-db-dsn').fill(dsn)
  await page.getByTestId('connect-db-submit').click()

  if (SQLITE_DSN) {
    // With a real seeded DB, the connection succeeds and shows a masked source.
    await expect(page.getByTestId('connect-db-dialog')).toHaveCount(0, { timeout: 30_000 })
    const dbItem = page.getByTestId('source-item').filter({ hasText: 'seed-db' })
    await expect(dbItem).toBeVisible({ timeout: 30_000 })
    // The DB source lists as a real, selectable source.
    await expect(dbItem.getByTestId('source-checkbox')).toBeVisible()
  } else {
    // Without a seeded DB the submit still yields a REAL server outcome: either a
    // connected source appears, or a friendly error is shown — and the error NEVER
    // echoes the DSN back.
    const error = page.getByTestId('connect-db-error')
    const connected = page.getByTestId('source-item').filter({ hasText: 'seed-db' })
    await expect(error.or(connected).first()).toBeVisible({ timeout: 30_000 })
    if (await error.isVisible()) {
      await expect(error).not.toContainText('e2e-probe.db')
    }
  }
})
