import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

const sample = Buffer.from(`# Order system migration

## 1 Approach
We moved the order system from one monolith to six microservices on Kubernetes.

## 2 Results
Deploys now take 6 minutes instead of 45. Users are much happier with the new system.
`)

test('upload → review → accept a note → download the Markdown feedback', async ({ page }) => {
  await page.goto('/')
  await page
    .getByLabel('choose a file')
    .setInputFiles({ name: 'report_en.md', mimeType: 'text/markdown', buffer: sample })
  await expect(page).toHaveURL(/\/documents\/\d+$/)

  await page.getByRole('button', { name: 'Start review' }).click()
  await expect(page.getByText('Reviewed', { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('heading', { name: 'Summary' })).toBeVisible()

  const note = page.locator('article.note').filter({ hasText: 'needs supporting data' }).first()
  await expect(note).toBeVisible()
  await note.getByRole('button', { name: 'Accept' }).click()
  await expect(note.getByRole('img', { name: 'Confirmed' })).toBeVisible()

  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Download Markdown' }).click()
  const file = await download
  expect(file.suggestedFilename()).toBe('report_en-review.md')
  const text = readFileSync(await file.path(), 'utf8')
  expect(text).toContain('needs supporting data')
})

test('a prompt without its required placeholder is refused', async ({ page }) => {
  await page.goto('/prompts')
  await page.getByRole('button', { name: /Section review/ }).click()
  const task = page.getByLabel('Task')
  await task.fill('Review this section carefully.')
  await expect(page.getByText(/Missing required placeholder: .*\{section\}/).first()).toBeVisible()
  await page.getByRole('button', { name: 'Save as new version' }).click()
  await expect(page.getByRole('alert')).toContainText('{section}')
})
