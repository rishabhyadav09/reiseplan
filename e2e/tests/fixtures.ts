import { test as base, expect, type Page } from '@playwright/test';

const CODE = process.env.UAT_TEST_CODE ?? 'round1-ci';

/** Everything past the gate needs a session, so make that the default. */
export const test = base.extend<{ app: Page }>({
  app: async ({ page }, use) => {
    await page.goto('/');
    // The gate only appears when UAT_CODES is set on the server. An ungated
    // build should still run the rest of the suite.
    const gate = page.getByTestId('access-code');
    if (await gate.isVisible().catch(() => false)) {
      await gate.fill(CODE);
      await page.getByTestId('enter').click();
    }
    await expect(page.getByTestId('compare')).toBeVisible();
    await use(page);
  },
});

export { expect };

export async function search(
  page: Page,
  opts: { from: string; to: string; preset?: string; bag?: boolean; dticket?: boolean },
) {
  await page.getByTestId('origin').fill(opts.from);
  await page.getByTestId('destination').fill(opts.to);
  if (opts.preset) await page.getByTestId('preset').selectOption(opts.preset);
  if (opts.bag) await page.getByTestId('bag').check();
  if (opts.dticket) await page.getByTestId('dticket').check();
  await page.getByTestId('compare').click();
  await expect(page.getByTestId('option').first()).toBeVisible();
}

/** "5h 30m" -> 330 */
export function minutes(text: string): number {
  const m = text.match(/(\d+)h\s*(\d+)m/);
  if (!m) throw new Error(`unparseable duration: ${text}`);
  return Number(m[1]) * 60 + Number(m[2]);
}

/** "€89.90" -> 8990 */
export function cents(text: string): number {
  const m = text.match(/([\d.,]+)/);
  if (!m) throw new Error(`unparseable price: ${text}`);
  return Math.round(Number(m[1].replace(',', '.')) * 100);
}
