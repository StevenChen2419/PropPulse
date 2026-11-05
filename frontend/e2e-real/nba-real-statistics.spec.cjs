const { test, expect } = require('@playwright/test');
const API = 'http://localhost:8000';

for (const nbaId of ['2544', '1627759', '203999']) {
  test(`authorized real NBA statistics ${nbaId}: source/API/UI and preservation`, async ({ page, request }, testInfo) => {
    const manifest = await (await request.get(`${API}/__test__/manifest`)).json();
    test.skip(!manifest.nba_real_statistics_demo, 'Requires separately authorized actual NBA payload artifact');
    const fixture = manifest.nba_real_statistics_demo.find(row => row.nba_player_id === nbaId);
    test.skip(!fixture, 'Selected player request did not return usable real statistics');
    expect(fixture.actual_source).toBe(true);
    const scope = `prop_id=${fixture.prop_id}&season=2025-26&competition=Regular%20Season`;
    const response = await request.get(`${API}/players/${fixture.player_id}/research?${scope}`);
    expect(response.ok()).toBe(true);
    const research = await response.json();
    const summary = research.season_summary;
    expect(research.selected_prop.id).toBe(fixture.prop_id);
    expect(research.selected_prop.event_id).toBe(fixture.event_id);
    expect(research.selected_prop.actionable).toBe(false);
    expect(summary.source).toBe('nba_com_stats');
    expect(summary.season).toBe('2025-26');
    expect(summary.competition).toBe('Regular Season');
    for (const key of ['latest_appearance', 'recorded_appearances', 'coverage_start', 'coverage_end']) {
      expect(summary[key]).toBe(fixture.oracle[key]);
    }
    const gap = Math.round((Date.parse(`${summary.reference_date}T00:00:00Z`) - Date.parse(`${fixture.oracle.latest_appearance}T00:00:00Z`)) / 86400000);
    expect(summary.calendar_day_gap).toBe(gap);
    expect(summary.full_intervening_days).toBe(Math.max(gap - 1, 0));
    for (const window of ['l5', 'l10']) {
      expect(summary[window].appearances).toBe(fixture.oracle[window].appearances);
      for (const metric of ['points', 'rebounds', 'assists', 'minutes']) {
        expect(summary[window][metric]).toEqual(fixture.oracle[window][metric]);
      }
    }
    // Historical appearances cannot establish today's selected team identity.
    expect(research.matchup_context.status).toBe('unavailable');
    expect(research.matchup_context.team_context).toBeNull();
    const forbidden = [];
    await page.route('**/*', route => {
      if (!['http://127.0.0.1:3199', API].includes(new URL(route.request().url()).origin)) {
        forbidden.push(route.request().url()); return route.abort();
      }
      return route.continue();
    });
    await page.goto(`/player/${fixture.player_id}?${scope}`);
    const section = page.getByRole('region', { name: 'Season statistics' });
    await expect(section).toBeVisible();
    await expect(section).toContainText('Historical season statistics; not current live form.');
    await expect(section).toContainText('2025-26 · Regular Season · NBA.com');
    await expect(section).toContainText(`${fixture.oracle.recorded_appearances} recorded appearances`);
    const appearanceLabel = new Intl.DateTimeFormat('en-US', {
      month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC',
    }).format(new Date(`${fixture.oracle.latest_appearance}T12:00:00Z`));
    await expect(section.locator('dl').filter({ hasText: 'Last recorded appearance' }).locator('dd').nth(0)).toHaveText(appearanceLabel);
    await expect(section.locator('dl').filter({ hasText: 'Last recorded appearance' }).locator('dd').nth(1)).toHaveText(String(gap));
    await expect(section.locator('dl').filter({ hasText: 'Last recorded appearance' }).locator('dd').nth(2)).toHaveText(String(Math.max(gap - 1, 0)));
    await expect(page.getByText(/Season summary above: 2025-26/)).toContainText('separate ESPN history');
    await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
    for (const [metric, label] of [['points','Points'],['rebounds','Rebounds'],['assists','Assists'],['minutes','Minutes']]) {
      const cells = section.getByRole('group', { name: label, exact: true }).locator('dd');
      for (const [index, window] of ['l5', 'l10'].entries()) {
        const stat = fixture.oracle[window][metric];
        await expect(cells.nth(index)).toContainText(stat.average.toFixed(1));
        await expect(cells.nth(index)).toContainText(`${stat.valid_samples}/${fixture.oracle[window].appearances} valid`);
      }
    }
    await expect(page.getByRole('region', { name: 'Matchup and team rest', exact: true })).toContainText(research.matchup_context.reason);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.reload();
    await expect(section).toContainText('Historical season statistics');
    await expect(page).toHaveURL(/season=2025-26/);
    expect(new URL(page.url()).searchParams.get('competition')).toBe('Regular Season');
    await page.screenshot({ path: testInfo.outputPath(`real-nba-${nbaId}.png`), fullPage: true });
    await page.goto(`/player/${fixture.player_id}?season=2025-26&competition=Regular%20Season`);
    await expect(section).toContainText(`${fixture.oracle.recorded_appearances} recorded appearances`);
    await expect(page.getByText(/Season summary above:/)).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const preserved = await (await request.get(`${API}/__test__/preservation`)).json();
    expect(preserved.unchanged).toBe(true);
    expect(preserved.provider_http_attempts).toBe(0);
    expect(forbidden).toEqual([]);
  });
}
