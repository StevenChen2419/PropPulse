const { test, expect } = require('@playwright/test');
const API = 'http://localhost:8000';

test('season summary hides the previous Prop during pending and failed same-player selection', async ({ page, request }) => {
  const manifest = await (await request.get(`${API}/__test__/manifest`)).json();
  const data = await (await request.get(`${API}/players/${manifest.player_id}/research?prop_id=${manifest.prop_id}`)).json();
  const alternate = data.available_props.find(prop => prop.id !== manifest.prop_id && prop.event_id === data.selected_prop.event_id);
  expect(alternate).toBeTruthy();
  const forbidden = [];
  await page.route('**/*', route => {
    if (!['http://127.0.0.1:3199', API].includes(new URL(route.request().url()).origin)) {
      forbidden.push(route.request().url()); return route.abort();
    }
    return route.continue();
  });
  await page.goto(`/player/${manifest.player_id}?prop_id=${manifest.prop_id}`);
  const summary = page.getByRole('region', { name: 'Season statistics' });
  await expect(summary).toBeVisible();
  let release, signalStarted;
  const pending = new Promise(resolve => { release = resolve; });
  const started = new Promise(resolve => { signalStarted = resolve; });
  const target = `${API}/players/${manifest.player_id}/research?prop_id=${alternate.id}`;
  const failSelection = async route => { signalStarted(); await pending; await route.abort('failed'); };
  await page.route(target, failSelection);
  try {
    await page.getByLabel('Research market').selectOption(alternate.id);
    await started;
    await expect(summary).toHaveCount(0);
    release();
    await expect(page.locator('p[role="alert"]')).toBeVisible();
    await expect(summary).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`prop_id=${alternate.id}$`));
  } finally { release(); await page.unroute(target, failSelection); }
  await page.reload();
  await expect(page.getByLabel('Research market')).toHaveValue(alternate.id);
  await expect(summary).toBeVisible();
  const preserved = await (await request.get(`${API}/__test__/preservation`)).json();
  expect(preserved.unchanged).toBe(true);
  expect(preserved.provider_http_attempts).toBe(0);
  expect(forbidden).toEqual([]);
});

test('invented NBA statistics: player-only summary, exact selection and preserved data', async ({ page, request }, testInfo) => {
  const manifest = await (await request.get(`${API}/__test__/manifest`)).json();
  const fixture = manifest.nba_statistics_demo;
  expect(fixture.synthetic).toBe(true);
  const before = await (await request.get(`${API}/__test__/snapshot`)).json();
  const forbidden = [];
  await page.route('**/*', route => {
    const req = route.request();
    if (!['http://127.0.0.1:3199', API].includes(new URL(req.url()).origin)) {
      forbidden.push(req.url()); return route.abort();
    }
    return route.continue();
  });
  await page.goto(`/player/${fixture.player_id}`);
  const summary = page.getByRole('region', { name: 'Season statistics' });
  await expect(summary).toBeVisible();
  await expect(summary).toContainText('NBA.com · NBA Stats');
  await expect(summary).toContainText('12 recorded appearances');
  await expect(summary).toContainText('4/5 valid');
  await expect(summary.getByRole('group', { name: 'Points', exact: true })).toContainText('4.0');
  await expect(summary.getByRole('group', { name: 'Points', exact: true })).toContainText('9.6');
  await expect(page.getByText('Fixture NBA Statistics (invented)')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.goto(`/player/${fixture.player_id}?prop_id=${fixture.prop_id}`);
  await expect(summary).toBeVisible();
  await expect(summary).toContainText('Full intervening days');
  const research = await (await request.get(`${API}/players/${fixture.player_id}/research?prop_id=${fixture.prop_id}`)).json();
  expect(research.selected_prop.id).toBe(fixture.prop_id);
  expect(research.selected_prop.event_id).toBe(fixture.event_id);
  expect(research.selected_prop.actionable).toBe(false);
  expect(research.season_summary.calendar_day_gap).toBe(5);
  expect(research.season_summary.full_intervening_days).toBe(4);
  await page.reload();
  await expect(summary).toContainText('12 recorded appearances');
  await page.screenshot({ path: testInfo.outputPath('nba-statistics.png'), fullPage: true });
  const after = await (await request.get(`${API}/__test__/preservation`)).json();
  expect(after.before).toEqual(before.before);
  expect(after.unchanged).toBe(true);
  expect(after.provider_http_attempts).toBe(0);
  expect(forbidden).toEqual([]);
});
