import { test, expect } from '@playwright/test'

const UUID = 'ec69c93f-036d-493a-93c9-81b87bf3e0a2'

test('saving a repositioned token updates the token image on the item view', async ({ page }) => {
  await page.goto(`/gm/view/${UUID}`)

  const tokenImg = page.locator('a[href$="/token"] img[alt="token"]')
  await expect(tokenImg).toBeVisible()
  const srcBefore = await tokenImg.getAttribute('src')

  await page.goto(`/gm/view/${UUID}/token`)
  await page.waitForSelector('canvas')

  // move the token so the saved PNG actually changes
  const slider = page.locator('input[type="range"]')
  await slider.fill('2')

  await page.getByRole('button', { name: /save/i }).click()

  // saveAndReturn navigates back to the item view once the save succeeds
  await page.waitForURL(`**/gm/view/${UUID}`)

  const srcAfter = await tokenImg.getAttribute('src')
  expect(srcAfter).not.toBe(srcBefore)
})
