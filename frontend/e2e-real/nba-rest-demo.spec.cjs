const { test, expect } = require('@playwright/test');

// Synthetic rehearsal and separately collected real observations stay distinct.
// Both use the real application/backend and disposable fixture-only navigation.
const API = 'http://localhost:8000';
let fixtures;
let realFixtures;
const observed = new WeakMap();

async function json(request, path) {
  const response = await request.get(`${API}${path}`);
  expect(response.ok(), `${path}: ${response.status()}`).toBeTruthy();
  return response.json();
}

function easternDate(value) {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/New_York',
  }).format(new Date(value));
}

test.beforeAll(async ({ request }) => {
  const manifest = await json(request, '/__test__/manifest');
  fixtures = manifest.nba_rest_demo || [];
  realFixtures = manifest.nba_real_rest_demo || [];
  // Exactly one source mode must be present. A missing/broken manifest must
  // fail rather than report a green run with every demonstration skipped.
  if (manifest.nba_real_statistics_demo) {
    expect(fixtures.length + realFixtures.length).toBe(0);
    expect(manifest.nba_real_statistics_demo.length).toBeGreaterThan(0);
    expect(manifest.nba_real_statistics_demo.every(row => row.actual_source === true)).toBe(true);
  } else {
    expect([[2, 0], [0, 2]]).toContainEqual([fixtures.length, realFixtures.length]);
  }
});

test.beforeEach(async ({ page }) => {
  const state = { blocked: [], writes: [], research: [] };
  observed.set(page, state);
  await page.route('**/*', route => {
    const request = route.request();
    const url = new URL(request.url());
    if (!['http://127.0.0.1:3199', API].includes(url.origin)) {
      state.blocked.push(url.href);
      return route.abort();
    }
    if (url.origin === API) {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) state.writes.push(url.pathname);
      if (url.pathname.endsWith('/research')) state.research.push(url);
    }
    return route.continue();
  });
});

test.afterEach(async ({ page }) => {
  expect(observed.get(page).blocked).toEqual([]);
  expect(observed.get(page).writes).toEqual([]);
});

for (const index of [0, 1]) {
  test(`synthetic NBA-shaped historical player ${index + 1}: exact selection, partial rest and unavailable minutes`, async ({ page, request }) => {
    test.skip(!fixtures.length, 'Synthetic rehearsal runs in isolated unit/PG; real browser dataset excludes invented same-date games.');
    const fixture = fixtures[index];
    expect(fixture.synthetic).toBe(true);
    const before = await json(request, '/__test__/snapshot');
    const research = await json(request, `/players/${fixture.player_id}/research?prop_id=${fixture.prop_id}`);
    expect(research.player_id).toBe(fixture.player_id);
    expect(research.selected_prop.id).toBe(fixture.prop_id);
    expect(research.selected_prop.event_id).toBe(fixture.event_id);
    expect(research.selected_prop.actionable).toBe(false);
    expect(research.selected_prop.over_odds).toBeNull();
    expect(research.selected_prop.under_odds).toBeNull();
    const rest = research.rest_workload;
    expect(rest.reference.prop_id).toBe(fixture.prop_id);
    expect(rest.reference.event_id).toBe(fixture.event_id);
    expect(new Date(rest.reference.at).toISOString()).toBe(new Date(fixture.reference_at).toISOString());
    expect(easternDate(rest.reference.at)).toBe('Jan 18, 2021');
    const verified = rest.verified;
    const appearance = verified.last_confirmed_appearance;
    expect(verified.status).toBe('partial');
    expect(appearance.provider).toBe('nba_com');
    expect(appearance.source).toBe('nba_api.stats.leaguegamelog');
    expect(appearance.participation_source).toBe('nba_api.stats.playergamelog');
    expect(appearance.time_precision).toBe('eastern_date');
    expect(appearance.completed_at).toBeNull();
    expect(easternDate(appearance.game_at)).toBe('Jan 15, 2021');
    expect(fixture.game_date).toBe('2021-01-15');
    expect(appearance.gap_days).toBe(3);
    expect(appearance.full_rest_days).toBe(2);
    expect(verified.provenance).toContain('nba_api.stats.playergamelog');
    expect(verified.context_team_id).toBeNull();
    expect(verified.last_completed_team_game).toBeNull();
    expect(verified.team_back_to_back).toBeNull();
    expect(verified.confirmed_missed_games).toBeNull();
    expect(verified.schedule_complete).toBe(false);
    expect(verified.evidence_counts.membership).toBe(0);
    expect(verified.evidence_counts.coverage).toBe(0);
    expect(rest.status).toBe('no_history');
    for (const window of [rest.workload.l5, rest.workload.l10, rest.workload.season]) {
      expect(window.average_minutes).toBeNull();
      expect(window.games).toBe(0);
    }
    expect(rest.workload.minutes_trend).toBeNull();

    const game = await json(request, `/props/game?event_id=${fixture.event_id}`);
    expect(game.props.some(prop => prop.id === fixture.prop_id)).toBe(false);
    await page.goto(`/player/${fixture.player_id}?prop_id=${fixture.prop_id}`);
    await page.getByText('Advanced participation & workload research', { exact: true }).click();
    await expect(page.getByRole('heading', { name: fixture.name, exact: true })).toBeVisible();
    await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
    await expect(page.getByLabel('Research game')).toHaveValue(`event:${fixture.event_id}`);
    const section = page.getByRole('region', { name: 'Rest & Workload', exact: true });
    const player = section.getByRole('region', { name: 'Player rest', exact: true });
    const team = section.getByRole('region', { name: 'Team schedule', exact: true });
    await expect(section.getByText(/Reference:.*Jan 18, 2021 \(Eastern\)/)).toBeVisible();
    await expect(player.getByText('Jan 15, 2021 · Partial coverage', { exact: true })).toBeVisible();
    await expect(player.getByText('3 / 2 days', { exact: true })).toBeVisible();
    await expect(player.getByText('Eastern calendar date only; actual game time unavailable.', { exact: true })).toBeVisible();
    await expect(player.locator('div').filter({ has: page.locator('dt', { hasText: 'Confirmed missed team games' }) }).getByText('Unknown', { exact: true })).toBeVisible();
    await expect(team.locator('dd')).toHaveText(['Unknown', 'Unknown', 'Unknown']);
    for (const label of ['Last 5 games', 'Last 10 games', 'Current season', 'Minutes trend']) {
      await expect(section.locator('div').filter({ has: page.locator('dt', { hasText: label }) }).last().getByText('Unavailable', { exact: true })).toBeVisible();
    }
    await section.getByText('Participation evidence & coverage', { exact: true }).click();
    await expect(section.getByText('Sources: nba_api.stats.leaguegamelog, nba_api.stats.playergamelog', { exact: true })).toBeVisible();
    await expect(section.getByText(/may not be the most recent actual games/)).toBeVisible();
    await page.screenshot({ path: test.info().outputPath(`synthetic-nba-rest-${fixture.nba_player_id}.png`), fullPage: true });
    await page.reload();
    await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
    await expect(page.getByLabel('Research game')).toHaveValue(`event:${fixture.event_id}`);
    await expect(page).toHaveURL(new RegExp(`/player/${fixture.player_id}\\?prop_id=${fixture.prop_id}$`));
    expect(observed.get(page).research.every(url => url.pathname === `/players/${fixture.player_id}/research` && url.searchParams.get('prop_id') === fixture.prop_id)).toBe(true);
    const after = await json(request, '/__test__/snapshot');
    expect(after.after).toEqual(before.after);
    expect(after.unchanged).toBe(true);
    expect(after.provider_http_attempts).toBe(0);
  });
}

for (const index of [0, 1]) {
  test(`collected real NBA observations player ${index + 1}: bounded historical appearance at collection-day diagnostic reference`, async ({ page, request }) => {
    test.skip(!realFixtures.length, 'Authorized normalized real observations were not supplied to this disposable fixture.');
    expect(realFixtures).toHaveLength(2);
    const fixture = realFixtures[index];
    expect(fixture.actual_source).toBe(true);
    const before = await json(request, '/__test__/snapshot');
    const research = await json(request, `/players/${fixture.player_id}/research?prop_id=${fixture.prop_id}`);
    expect(research.player_id).toBe(fixture.player_id);
    expect(research.selected_prop.id).toBe(fixture.prop_id);
    expect(research.selected_prop.event_id).toBe(fixture.event_id);
    expect(research.selected_prop.actionable).toBe(false);
    expect(research.selected_prop.over_odds).toBeNull();
    expect(research.selected_prop.under_odds).toBeNull();
    const rest = research.rest_workload;
    expect(rest.reference.prop_id).toBe(fixture.prop_id);
    expect(rest.reference.event_id).toBe(fixture.event_id);
    expect(new Date(rest.reference.at).toISOString()).toBe(new Date(fixture.reference_at).toISOString());
    const verified = rest.verified;
    const appearance = verified.last_confirmed_appearance;
    expect(verified.status).toBe('partial');
    expect(appearance.provider).toBe('nba_com');
    expect(appearance.source).toBe('nba_api.stats.leaguegamelog');
    expect(appearance.participation_source).toBe('nba_api.stats.playergamelog');
    expect(appearance.time_precision).toBe('eastern_date');
    expect(appearance.completed_at).toBeNull();
    expect(new Date(appearance.observed_at).toISOString()).toBe('2026-10-18T20:58:08.542Z');
    expect(appearance.participation_observed_at).toBe(appearance.observed_at);
    expect(easternDate(appearance.game_at)).toBe('Jan 15, 2021');
    expect(fixture.game_date).toBe('2021-01-15');
    // Date.UTC uses calendar components only, independently of service arithmetic.
    const referenceParts = new Intl.DateTimeFormat('en-CA', {
      year: 'numeric', month: '2-digit', day: '2-digit', timeZone: 'America/New_York',
    }).formatToParts(new Date(fixture.reference_at));
    const component = name => Number(referenceParts.find(part => part.type === name).value);
    const gap = (Date.UTC(component('year'), component('month') - 1, component('day')) - Date.UTC(2021, 0, 15)) / 86_400_000;
    expect(appearance.gap_days).toBe(gap);
    expect(appearance.full_rest_days).toBe(gap - 1);
    expect(verified.provenance).toEqual(['nba_api.stats.leaguegamelog', 'nba_api.stats.playergamelog']);
    expect(verified.context_team_id).toBeNull();
    expect(verified.last_completed_team_game).toBeNull();
    expect(verified.team_back_to_back).toBeNull();
    expect(verified.confirmed_missed_games).toBeNull();
    expect(verified.schedule_complete).toBe(false);
    expect(rest.status).toBe('no_history');
    for (const window of [rest.workload.l5, rest.workload.l10, rest.workload.season]) {
      expect(window.average_minutes).toBeNull();
      expect(window.games).toBe(0);
    }
    expect(rest.workload.minutes_trend).toBeNull();
    const historical = await json(request, `/players/${fixture.player_id}/research?prop_id=${fixture.historical_prop_id}`);
    expect(historical.selected_prop.id).toBe(fixture.historical_prop_id);
    expect(historical.selected_prop.event_id).toBe(fixture.historical_event_id);
    expect(historical.rest_workload.verified.last_confirmed_appearance).toBeNull();

    const game = await json(request, `/props/game?event_id=${fixture.event_id}`);
    expect(game.props.some(prop => prop.id === fixture.prop_id)).toBe(false);
    await page.goto(`/player/${fixture.player_id}?prop_id=${fixture.prop_id}`);
    await page.getByText('Advanced participation & workload research', { exact: true }).click();
    await expect(page.getByRole('heading', { name: fixture.name, exact: true })).toBeVisible();
    await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
    await expect(page.getByLabel('Research game')).toHaveValue(`event:${fixture.event_id}`);
    const section = page.getByRole('region', { name: 'Rest & Workload', exact: true });
    const player = section.getByRole('region', { name: 'Player rest', exact: true });
    const team = section.getByRole('region', { name: 'Team schedule', exact: true });
    await expect(section.getByText(new RegExp(`Reference:.*${easternDate(fixture.reference_at)} \\(Eastern\\)`))).toBeVisible();
    await expect(page.getByLabel('Research game').locator('option:checked')).toHaveText(/Collection-day diagnostic; old coverage only/);
    await expect(player.getByText('Jan 15, 2021 · Partial coverage', { exact: true })).toBeVisible();
    await expect(player.getByText(`${gap} / ${gap - 1} days`, { exact: true })).toBeVisible();
    await expect(player.getByText('Eastern calendar date only; actual game time unavailable.', { exact: true })).toBeVisible();
    await expect(player.locator('div').filter({ has: page.locator('dt', { hasText: 'Confirmed missed team games' }) }).getByText('Unknown', { exact: true })).toBeVisible();
    await expect(team.locator('dd')).toHaveText(['Unknown', 'Unknown', 'Unknown']);
    for (const label of ['Last 5 games', 'Last 10 games', 'Minutes trend']) {
      await expect(section.locator('div').filter({ has: page.locator('dt', { hasText: label }) }).last().getByText('Unavailable', { exact: true })).toBeVisible();
    }
    await section.getByText('Participation evidence & coverage', { exact: true }).click();
    await expect(section.getByText('Sources: nba_api.stats.leaguegamelog, nba_api.stats.playergamelog', { exact: true })).toBeVisible();
    await expect(section.getByText(/may not be the most recent actual games/)).toBeVisible();
    await page.screenshot({ path: test.info().outputPath(`real-bounded-nba-rest-${fixture.nba_player_id}.png`), fullPage: true });
    await page.reload();
    await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
    await expect(page.getByLabel('Research game')).toHaveValue(`event:${fixture.event_id}`);
    await page.goto(`/player/${fixture.player_id}?prop_id=${fixture.historical_prop_id}`);
    await page.getByText('Advanced participation & workload research', { exact: true }).click();
    await expect(page.getByLabel('Research market')).toHaveValue(fixture.historical_prop_id);
    await expect(page.getByLabel('Research game')).toHaveValue(`event:${fixture.historical_event_id}`);
    await expect(player.locator('dd').first()).toHaveText('Unknown');
    await expect(page).toHaveURL(new RegExp(`prop_id=${fixture.historical_prop_id}$`));
    const after = await json(request, '/__test__/snapshot');
    expect(after.after).toEqual(before.after);
    expect(after.unchanged).toBe(true);
    expect(after.provider_http_attempts).toBe(0);
  });
}
