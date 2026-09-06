import { test, expect, search, minutes, cents } from './fixtures';

test.describe('the invite gate', () => {
  test('a stranger cannot reach the planner', async ({ page }) => {
    await page.goto('/');
    const gate = page.getByTestId('access-code');
    test.skip(!(await gate.isVisible().catch(() => false)), 'build is ungated');
    await expect(page.getByTestId('compare')).toBeHidden();
  });

  test('a wrong code is refused and says so @smoke', async ({ page }) => {
    await page.goto('/');
    const gate = page.getByTestId('access-code');
    test.skip(!(await gate.isVisible().catch(() => false)), 'build is ungated');
    await gate.fill('definitely-not-a-code');
    await page.getByTestId('enter').click();
    await expect(page.getByTestId('gate-error')).toContainText(/not valid/i);
    await expect(page.getByTestId('compare')).toBeHidden();
  });

  test('a session survives a reload so testers enter the code once', async ({ app }) => {
    await app.reload();
    await expect(app.getByTestId('compare')).toBeVisible();
    await expect(app.getByTestId('who')).toContainText(/signed in as/i);
  });
});

test.describe('search criteria', () => {
  test('Dortmund to München ranks the train first and shows the flight losing @smoke', async ({ app }) => {
    await search(app, { from: 'Dortmund', to: 'München', preset: 'balanced' });

    const first = app.getByTestId('option').first();
    await expect(first).toHaveAttribute('data-mode', 'rail');

    const air = app.locator('[data-testid=option][data-mode=air]');
    await expect(air).toHaveCount(1);

    // The whole product thesis: the flight is not meaningfully faster
    // door to door, and it costs more.
    const railMin = minutes(await first.getByTestId('duration').innerText());
    const airMin = minutes(await air.getByTestId('duration').innerText());
    expect(airMin).toBeGreaterThan(railMin - 90);
    expect(cents(await air.getByTestId('price').innerText()))
      .toBeGreaterThan(cents(await first.getByTestId('price').innerText()));
  });

  test('Berlin to Hamburg offers no flight at all @smoke', async ({ app }) => {
    await search(app, { from: 'Berlin', to: 'Hamburg' });
    await expect(app.locator('[data-testid=option][data-mode=air]')).toHaveCount(0);
  });

  test('Dortmund to Essen offers neither flight nor coach', async ({ app }) => {
    await search(app, { from: 'Dortmund', to: 'Essen' });
    await expect(app.locator('[data-testid=option][data-mode=air]')).toHaveCount(0);
    await expect(app.locator('[data-testid=option][data-mode=coach]')).toHaveCount(0);
    await expect(app.getByTestId('option')).not.toHaveCount(0);
  });

  test('an unknown city fails with a message, not a blank screen', async ({ app }) => {
    await search(app, { from: 'Berlin', to: 'Berlin' }).catch(() => {});
    await app.getByTestId('destination').fill('Atlantis');
    await app.getByTestId('compare').click();
    await expect(app.locator('.msg')).toBeVisible();
  });

  test.describe('presets change the winner', () => {
    for (const preset of ['cheapest', 'fastest', 'balanced', 'laptop', 'low_carbon']) {
      test(`${preset} returns a ranked, non-empty result`, async ({ app }) => {
        await search(app, { from: 'Köln', to: 'Berlin', preset });
        const opts = app.getByTestId('option');
        expect(await opts.count()).toBeGreaterThan(1);
        await expect(opts.first()).toContainText('100% match');
      });
    }

    test('cheapest never returns a dearer winner than fastest', async ({ app }) => {
      await search(app, { from: 'Dortmund', to: 'München', preset: 'cheapest' });
      const cheap = cents(await app.getByTestId('price').first().innerText());
      await search(app, { from: 'Dortmund', to: 'München', preset: 'fastest' });
      const fast = cents(await app.getByTestId('price').first().innerText());
      expect(cheap).toBeLessThanOrEqual(fast);
    });
  });

  test('checking a bag makes the flight slower and dearer', async ({ app }) => {
    await search(app, { from: 'München', to: 'Hamburg', preset: 'fastest' });
    const air = app.locator('[data-testid=option][data-mode=air]');
    const before = {
      min: minutes(await air.getByTestId('duration').innerText()),
      c: cents(await air.getByTestId('price').innerText()),
    };

    await app.getByTestId('bag').check();
    await app.getByTestId('compare').click();
    await expect(app.getByTestId('option').first()).toBeVisible();

    expect(minutes(await air.getByTestId('duration').innerText())).toBeGreaterThan(before.min);
    expect(cents(await air.getByTestId('price').innerText())).toBeGreaterThan(before.c);
  });

  test('a Deutschlandticket holder is shown a zero-fare option @smoke', async ({ app }) => {
    await search(app, {
      from: 'Frankfurt am Main', to: 'Stuttgart',
      preset: 'cheapest', dticket: true,
    });
    await expect(app.getByTestId('option').first().getByTestId('price'))
      .toHaveText('€0.00');
  });
});

test.describe('the breakdown', () => {
  test('every option explains where the time and the money went', async ({ app }) => {
    await search(app, { from: 'Dortmund', to: 'München' });
    const first = app.getByTestId('option').first();
    await first.getByRole('group').getByText(/where the time/i).click();

    const rows = first.locator('table tr');
    expect(await rows.count()).toBeGreaterThan(3);
    await expect(first).toContainText(/door to door/i);
  });

  test('the flight names its fare as modelled rather than quoted', async ({ app }) => {
    await search(app, { from: 'München', to: 'Hamburg' });
    await expect(app.locator('[data-testid=option][data-mode=air]'))
      .toContainText(/modelled/i);
  });

  test('rail carries a live fare badge', async ({ app }) => {
    await search(app, { from: 'Köln', to: 'Berlin' });
    await expect(app.locator('[data-testid=option][data-mode=rail]').first())
      .toContainText(/live fare/i);
  });
});

test.describe('UAT feedback', () => {
  test('a tester can file a verdict and gets confirmation @smoke', async ({ app }) => {
    await search(app, { from: 'Dortmund', to: 'München' });
    await expect(app.getByTestId('feedback')).toBeVisible();

    // Nothing can be sent until a verdict is chosen.
    await expect(app.getByTestId('feedback-send')).toBeDisabled();

    await app.getByTestId('verdict-wrong').click();
    await app.getByTestId('feedback-comment')
      .fill('I would have flown — I do not want to change at Hannover.');
    await app.getByTestId('feedback-send').click();

    await expect(app.getByTestId('feedback-status')).toContainText(/logged/i);
  });

  test('the feedback form resets for the next search', async ({ app }) => {
    await search(app, { from: 'Berlin', to: 'Hamburg' });
    await app.getByTestId('verdict-right').click();
    await search(app, { from: 'Köln', to: 'Berlin' });
    await expect(app.getByTestId('feedback-send')).toBeDisabled();
  });
});

test.describe('quality floor', () => {
  test('the whole form is reachable by keyboard alone', async ({ app }) => {
    await app.getByTestId('origin').focus();
    for (let i = 0; i < 12; i++) {
      const tag = await app.evaluate(() => document.activeElement?.getAttribute('data-testid'));
      if (tag === 'compare') return;
      await app.keyboard.press('Tab');
    }
    throw new Error('never reached the compare button by tabbing');
  });

  test('results are readable on a narrow screen without sideways scrolling @smoke', async ({ app }) => {
    await app.setViewportSize({ width: 375, height: 780 });
    await search(app, { from: 'Dortmund', to: 'München' });
    const overflow = await app.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });

  test('no console errors during a normal search @smoke', async ({ app }) => {
    const errors: string[] = [];
    app.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    await search(app, { from: 'Köln', to: 'Berlin' });
    expect(errors).toEqual([]);
  });
});
