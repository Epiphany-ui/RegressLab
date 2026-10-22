import { test, expect } from '@playwright/test'
import { readFileSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

const example = name => resolve(import.meta.dirname, '../examples', name)

test('fixture metrics, filtering, exports and persisted history', async ({ page }, testInfo) => {
  const browserErrors = []
  page.on('pageerror', err => browserErrors.push(err.message))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '模型升级检查' })).toBeVisible()
  await page.getByRole('button', { name: '载入工程夹具', exact: true }).click()
  await expect(page.getByRole('heading', { name: /成对指标 · 12例工程夹具/ })).toBeVisible()
  await expect(page.getByText('−16.7', { exact: false })).toBeVisible()
  await expect(page.getByText('旧 75.0%', { exact: true })).toBeVisible()
  await expect(page.getByText('新 58.3%', { exact: true })).toBeVisible()
  await expect(page.getByText('仅描述：未达到可确认门禁')).toBeVisible()
  await expect(page.getByText('当前没有满足条件的候选分组')).toBeVisible()
  if (testInfo.project.name === 'mobile') {
    const rows = await page.locator('.boundary-row').evaluateAll(elements => elements.map(element => ({ x: element.getBoundingClientRect().x, y: element.getBoundingClientRect().y, width: element.getBoundingClientRect().width })))
    expect(rows).toHaveLength(3)
    expect(rows.every(row => row.width > 250 && Math.abs(row.x - rows[0].x) < 1)).toBe(true)
    expect(rows[0].y < rows[1].y && rows[1].y < rows[2].y).toBe(true)
    expect((await page.getByRole('button', { name: '导入预测对比', exact: true }).boundingBox()).height).toBeGreaterThanOrEqual(44)
  }
  await expect(page.locator('.cases-table tbody tr')).toHaveCount(6)
  await page.getByRole('button', { name: '下一页' }).click()
  await expect(page.locator('.pagination')).toContainText('7–12')
  await page.locator('.filter-tabs button').filter({ hasText: '负向翻转' }).click()
  await expect(page.locator('.cases-table tbody tr')).toHaveCount(3)
  await expect(page.locator('.pagination')).toContainText('共 3 条')

  for (const format of ['JSON', 'HTML']) {
    await page.getByRole('button', { name: '导出报告' }).click()
    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('button', { name: format === 'JSON' ? /JSON 结构化报告/ : /HTML 可读报告/ }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toMatch(new RegExp(`\\.${format.toLowerCase()}$`))
    const text = readFileSync(await download.path(), 'utf8')
    expect(text).toContain('DESCRIPTIVE_ONLY')
    expect(text).not.toContain('"private"')
    if (format === 'JSON') {
      const data = JSON.parse(text)
      expect(data.analysis.metrics.discovery).toMatchObject({ n: 12, a: 6, b: 3, c: 1, d: 2 })
      expect(data.analysis.metrics.confirmation).toBeNull()
      expect(data.discovery_cases).toHaveLength(12)
    }
  }
  await page.reload()
  await expect(page.getByRole('heading', { name: /成对指标 · 12例工程夹具/ })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)
  expect(overflow).toBe(false)
  mkdirSync(resolve(import.meta.dirname, '../docs/screenshots'), { recursive: true })
  await page.screenshot({ path: resolve(import.meta.dirname, `../docs/screenshots/demo-${testInfo.project.name}.png`), fullPage: true })
  expect(browserErrors).toEqual([])
})

test('real multipart upload, validation failure and default grouping', async ({ page }, testInfo) => {
  await page.goto('/')
  await page.getByRole('button', { name: '导入预测对比', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.locator('#analysis-name').fill(`浏览器上传验收 · ${testInfo.project.name}`)
  await dialog.locator('#old-model').fill('declared-old')
  await dialog.locator('#new-model').fill('declared-new')
  await dialog.locator('#source-url').fill('https://example.org/synthetic-fixture')
  await dialog.locator('#source-version').fill('browser-fixture-v1')
  await dialog.locator('#source-license').fill('Project synthetic fixture')
  await dialog.locator('#dataset_file').setInputFiles(example('dataset.jsonl'))
  await dialog.locator('#old_predictions_file').setInputFiles(example('old-predictions.jsonl'))
  const partial = readFileSync(example('new-predictions.jsonl'), 'utf8').trim().split('\n').slice(1).join('\n') + '\n'
  await dialog.locator('#new_predictions_file').setInputFiles({ name: 'missing-row.jsonl', mimeType: 'application/x-ndjson', buffer: Buffer.from(partial) })
  await dialog.getByRole('button', { name: '校验并创建分析' }).click()
  await expect(dialog.getByText('导入未完成', { exact: true })).toBeVisible()
  await expect(dialog.locator('.modal-error')).toContainText('完整合法覆盖')
  await dialog.locator('#new_predictions_file').setInputFiles(example('new-predictions.jsonl'))
  await dialog.getByRole('button', { name: '校验并创建分析' }).click()
  await expect(dialog).not.toBeVisible()
  await expect(page.getByRole('heading', { name: new RegExp(`浏览器上传验收 · ${testInfo.project.name}`) })).toBeVisible()
  await expect(page.locator('.source-detail')).toContainText('https://example.org/synthetic-fixture')
  await expect(page.locator('.source-detail')).toContainText('browser-fixture-v1')
  await page.getByRole('button', { name: /体验分组夹具/ }).click()
  await expect(page.getByRole('heading', { name: /分组发现 · 合成工程夹具/ })).toBeVisible()
  await expect(page.locator('#groups tbody tr')).toHaveCount(6)
  await expect(page.locator('#groups tbody')).toContainText('尚未独立确认')
  await expect(page.locator('#groups tbody')).toContainText('50.0 个百分点')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false)
})

test('a slow history request blocks starting an import until its result is ready', async ({ page, request }, testInfo) => {
  const basic = await (await request.post('/api/demo/fixture')).json()
  await request.post('/api/demo/fixture?kind=discovery')
  await page.goto('/')
  await expect(page.getByRole('heading', { name: /分组发现 · 合成工程夹具/ })).toBeVisible()
  await page.route(`**/api/demo/analyses/${basic.id}`, async route => {
    await new Promise(resolve => setTimeout(resolve, 500))
    await route.continue()
  })
  if (testInfo.project.name === 'mobile') await page.getByRole('button', { name: '打开导航' }).click()
  const response = page.waitForResponse(res => res.url().endsWith(`/api/demo/analyses/${basic.id}`))
  await page.locator('.history-item').filter({ hasText: '成对指标 · 12例工程夹具' }).first().click()
  await expect(page.getByRole('button', { name: '导入预测对比', exact: true })).toBeDisabled()
  await response
  await expect(page.getByRole('button', { name: '导入预测对比', exact: true })).toBeEnabled()
  await expect(page.locator('.analysis-title')).toContainText('成对指标 · 12例工程夹具')
})
