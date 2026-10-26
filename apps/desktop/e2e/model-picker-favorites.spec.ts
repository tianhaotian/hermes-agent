import { type MockBackendFixture, setupMockBackend, waitForAppReady } from './fixtures'
import { expect, test } from './test'

let fixture: MockBackendFixture | null = null

test.beforeAll(async () => {
  fixture = await setupMockBackend({
    mockServer: { extraModels: Array.from({ length: 30 }, (_, i) => `choice-${String(i).padStart(2, '0')}`) }
  })
  await waitForAppReady(fixture, 120_000)
})

test.afterAll(async () => {
  await fixture?.cleanup()
  fixture = null
})

test('keeps favorites in view when reopening a long model catalog', async () => {
  const page = fixture!.page
  const picker = page.locator('[data-tour="model-pill"]')

  await picker.click()
  const search = page.getByRole('menu').getByRole('textbox')
  await search.fill('choice-00')
  const first = page.getByRole('menuitem').filter({ hasText: /choice[ -]00/i })
  await first.click({ modifiers: ['Shift'] })
  await search.fill('choice-29')
  await search.press('Enter')
  await expect(search).toHaveCount(0)
  await expect(picker).toContainText('Choice 29')

  await picker.click()
  const favorite = page.getByRole('menuitem').filter({ hasText: /choice[ -]00/i })
  await expect(favorite).toHaveCount(1)
  await page.screenshot({ path: test.info().outputPath('favorites-on-open.png') })
  // Visibility alone ignores overflow clipping. The actual favorite row must
  // intersect the scroll viewport without a click scrolling it into view.
  await expect(favorite).toBeInViewport({ ratio: 1 })

  await search.press('ArrowUp')
  await expect(page.locator('[data-kb-active]')).toBeInViewport({ ratio: 1 })
  await search.fill('choice-00')
  await expect(favorite).toBeInViewport({ ratio: 1 })
  await search.press('Escape')

  await picker.click()
  await expect(favorite).toBeInViewport({ ratio: 1 })

  await favorite.click({ modifiers: ['Shift'] })
  await search.press('Escape')
  await picker.click()
  await expect(page.locator('[data-kb-active]')).toContainText('Choice 29')
  await expect(page.locator('[data-kb-active]')).toBeInViewport({ ratio: 1 })
})
