const { test, expect } = require('@playwright/test');
const fixtures = require('../tests/fixtures/multi-sport-research.json');

for (const fixture of fixtures) for (const mobile of [false, true]) {
  test(`${fixture.sport} ${fixture.role} statistics and season navigation ${mobile ? 'mobile' : 'desktop'} (invented)`, async ({ page }) => {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 });
    const unexpected = [], requests = [];
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin === 'http://127.0.0.1:3199') return route.continue();
      if (!['http://localhost:8000','http://127.0.0.1:8199'].includes(url.origin)) { unexpected.push(url.origin); return route.abort(); }
      const json = body => route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': 'http://127.0.0.1:3199', 'access-control-allow-credentials': 'true' }, body: JSON.stringify(body) });
      if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: { 'access-control-allow-origin': 'http://127.0.0.1:3199', 'access-control-allow-credentials': 'true', 'access-control-allow-headers': 'Content-Type,X-CSRF-Token', 'access-control-allow-methods': 'GET' } });
      requests.push(url);
      if (url.pathname === '/users/me') return route.fulfill({ status: 401, headers: { 'access-control-allow-origin': 'http://127.0.0.1:3199', 'access-control-allow-credentials': 'true' }, body: '{}' });
      if (url.pathname === `/players/${fixture.player_id}`) return json({ id: fixture.player_id,
        name: `Invented ${fixture.sport} ${fixture.role} fixture`, team: 'Fixture team', team_abbr: 'FIX', sport: fixture.sport, fatigue: null, props: [] });
      if (url.pathname === `/players/${fixture.player_id}/research`) {
        const selected = url.searchParams.get('season');
        const summary = selected && selected !== fixture.season ? { ...fixture.summary, season: selected, status: 'unavailable', recorded_appearances: 0 } : fixture.summary;
        return json({ player_id: fixture.player_id, sport: fixture.sport, available_props: [], selected_prop: null, selection_available: false,
          trends: null, splits: null, line_movement: null, games: [], history: null, rest_workload: null, matchup_context: null, season_summary: summary });
      }
      unexpected.push(url.pathname); return route.abort();
    });
    await page.goto(`/player/${fixture.player_id}?season=${fixture.season}`);
    const summary = page.getByRole('region', { name: 'Season statistics' });
    await expect(summary).toBeVisible();
    await expect(summary).toContainText('Invented offline fixture; not live sports coverage.');
    const metrics = fixture.summary.metrics || [{ label: 'Points' }, { label: 'Rebounds' }, { label: 'Assists' }, { label: 'Minutes' }];
    for (const metric of metrics) await expect(summary.getByRole('group', { name: metric.label, exact: true })).toBeVisible();
    if (!['NBA','WNBA'].includes(fixture.sport)) await expect(summary.getByRole('group', { name: 'Rebounds', exact: true })).toHaveCount(0);
    if (fixture.role === 'goalie') await expect(summary.getByRole('group', { name: 'Goals', exact: true })).toHaveCount(0);
    if (fixture.role === 'pitcher') await expect(summary.getByRole('group', { name: 'Hits', exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: test.info().outputPath(`${fixture.sport}-${fixture.role}.png`), fullPage: true });
    const nextSeason = ['NBA','NHL'].includes(fixture.sport) ? '2026-27' : '2026';
    await page.getByLabel(`${fixture.sport} statistics season`).selectOption(nextSeason);
    await expect(summary).toContainText('Season statistics unavailable');
    await expect(page).toHaveURL(new RegExp(`season=${nextSeason}`));
    expect(requests.some(url => url.searchParams.get('season') === nextSeason)).toBe(true);
    await page.reload();
    await expect(summary).toContainText('Season statistics unavailable');
    expect(unexpected).toEqual([]); expect(errors).toEqual([]);
  });
}
