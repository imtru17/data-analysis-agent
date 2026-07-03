import { test, expect } from '@playwright/test'
import path from 'node:path'

// Phase-1 E2E smoke test. Drives the BUILT app served by the running FastAPI
// backend at http://localhost:8001/app/ (see playwright.config.ts). It uploads a
// real CSV, asks a real question against the real agent, and asserts on real
// content — the step chips animate, a non-empty answer renders, and the code
// panel reveals the pandas snippet. This is a content assertion, not a 200 check.

// Playwright runs specs in a CommonJS context, so __dirname is available.
const CSV_FIXTURE = path.join(__dirname, 'fixtures', 'sales.csv')

test('upload a CSV, ask a question, watch steps, read the answer, inspect the code', async ({ page }) => {
  await page.goto('/app/')

  // The workspace loads, styled: the composer is disabled until a dataset loads.
  await expect(page.getByTestId('composer-input')).toBeDisabled()
  await expect(page.getByTestId('thread-empty')).toBeVisible()

  // Upload the CSV via the hidden file input behind the dropzone.
  await page.getByTestId('file-input').setInputFiles(CSV_FIXTURE)

  // The profile system message appears with the real schema (columns from the CSV).
  const profile = page.getByTestId('profile-message')
  await expect(profile).toBeVisible({ timeout: 30_000 })
  await expect(profile).toContainText('sales.csv')
  await expect(page.getByTestId('schema-table')).toContainText('revenue')
  await expect(page.getByTestId('schema-table')).toContainText('region')

  // The composer is now enabled.
  const input = page.getByTestId('composer-input')
  await expect(input).toBeEnabled()

  // Ask a real question.
  await input.fill('What is the total revenue by region?')
  await page.getByTestId('send-button').click()

  // The user message echoes, and an agent turn with the live step trace appears.
  await expect(page.getByTestId('user-message').last()).toContainText('total revenue by region')
  const agent = page.getByTestId('agent-message').last()
  await expect(agent).toBeVisible()
  await expect(agent.getByTestId('step-trace')).toBeVisible()

  // At least one step chip reaches a terminal state as events stream in.
  await expect(async () => {
    const statuses = await agent.locator('[data-testid^="step-chip-"]').evaluateAll(els =>
      els.map(el => el.getAttribute('data-status')),
    )
    expect(statuses.some(s => s === 'done' || s === 'running' || s === 'error')).toBe(true)
  }).toPass({ timeout: 60_000 })

  // The run completes with a non-empty answer (real LLM content).
  await expect(agent).toHaveAttribute('data-status', 'completed', { timeout: 120_000 })
  const answer = agent.getByTestId('answer-text')
  await expect(answer).toBeVisible()
  await expect(answer).not.toBeEmpty()
  const answerText = (await answer.innerText()).trim()
  expect(answerText.length).toBeGreaterThan(10)

  // The final 'Answering' chip has flipped to done.
  await expect(agent.getByTestId('step-chip-answer')).toHaveAttribute('data-status', 'done')

  // The code panel is collapsed by default, then reveals the pandas snippet.
  await expect(agent.getByTestId('code-panel')).toHaveCount(0)
  await agent.getByTestId('show-code-toggle').click()
  const codePanel = agent.getByTestId('code-panel')
  await expect(codePanel).toBeVisible()
  const code = (await agent.getByTestId('code-content').innerText()).trim()
  expect(code.length).toBeGreaterThan(0)
  expect(code).toContain('result')
})

test('still-deferred stubs are visibly inert, not broken', async ({ page }) => {
  await page.goto('/app/')

  // History remains a labelled stub (Phase 3). The "Today:" cost is now REAL.
  await expect(page.getByTestId('history-button')).toHaveAttribute('aria-disabled', 'true')

  // The right-rail coming-soon panel restates the remaining Phase-3 roadmap.
  await expect(page.getByTestId('coming-soon-rail')).toBeVisible()
  await expect(page.getByTestId('rail-connect-db')).toHaveAttribute('aria-disabled', 'true')

  // Every Soon pill carries the marking; the add-source stub is disabled.
  await expect(page.getByTestId('add-source')).toBeDisabled()
  expect(await page.getByTestId('soon-pill').count()).toBeGreaterThan(0)
})
