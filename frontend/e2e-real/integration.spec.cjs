const { test, expect } = require('@playwright/test');

const API = 'http://localhost:8000';
let fixture;
const observed = new WeakMap();

test.beforeAll(async ({ request }) => {
  const response = await request.get(`${API}/__test__/manifest`);
  expect(response.ok()).toBeTruthy();
  fixture = await response.json();
});

test.beforeEach(async ({ page }) => {
  const state = { blocked: [], research: [], writes: [] };
  observed.set(page, state);
  // Allow actual frontend/backend traffic; fail closed for external requests.
  await page.route('**/*', route => {
    const request = route.request();
    const url = new URL(request.url());
    if (!['http://127.0.0.1:3199', API].includes(url.origin)) {
      state.blocked.push(url.href);
      return route.abort();
    }
    if (url.origin === API) {
      if (url.pathname.endsWith('/research')) state.research.push(url);
      if (!['GET', 'OPTIONS', 'HEAD'].includes(request.method())) state.writes.push(url.pathname);
    }
    return route.continue();
  });
});

test.afterEach(async ({ page }) => {
  expect(observed.get(page).blocked).toEqual([]);
  expect(observed.get(page).writes).toEqual([]);
});

async function json(request, path) {
  const response = await request.get(`${API}${path}`);
  expect(response.ok(), `${path}: ${response.status()}`).toBeTruthy();
  return response.json();
}

test('Home → one authoritative game → exact player research and reload', async ({ page, request }) => {
  const games = await json(request, '/props/todays-games');
  expect(games.filter(game => game.event_id === fixture.event_id)).toHaveLength(1);
  const detail = await json(request, `/props/game?event_id=${fixture.event_id}`);
  expect(detail.props).toHaveLength(10);
  expect(new Set(detail.props.map(prop => prop.event_id))).toEqual(new Set([fixture.event_id]));
  await page.goto('/');
  const game = page.locator(`a[href="/games/${fixture.event_id}"]`);
  await expect(game).toHaveCount(1);
  await game.click();
  await expect(page).toHaveURL(new RegExp(`/games/${fixture.event_id}$`));
  await page.reload();
  const prop = page.locator(`a[href="/player/${fixture.player_id}?prop_id=${fixture.prop_id}"]`);
  await expect(prop).toBeVisible();
  await prop.click();
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
  await page.reload();
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
  await page.screenshot({ path: test.info().outputPath('real-research.png'), fullPage: true });
});

test('two players and their markets share the exact Event', async ({ page, request }) => {
  for (const [player, prop] of [[fixture.player_id, fixture.prop_id], [fixture.second_player_id, fixture.second_player_prop_id]]) {
    const research = await json(request, `/players/${player}/research?prop_id=${prop}`);
    expect(research.selected_prop.id).toBe(prop);
    expect(research.selected_prop.event_id).toBe(fixture.event_id);
    await page.goto(`/player/${player}?prop_id=${prop}`);
    await expect(page.getByLabel('Research market')).toHaveValue(prop);
    await expect(page.getByLabel('Research game')).toHaveValue(`event:${fixture.event_id}`);
  }
});

test('identical market and line in different Events retain distinct Prop UUIDs', async ({ page, request }) => {
  const first = await json(request, `/players/${fixture.player_id}/research?prop_id=${fixture.prop_id}`);
  const second = await json(request, `/players/${fixture.player_id}/research?prop_id=${fixture.other_event_prop_id}`);
  expect(first.selected_prop.prop_type).toBe(second.selected_prop.prop_type);
  expect(first.selected_prop.line).toBe(second.selected_prop.line);
  expect(second.selected_prop.event_id).toBe(fixture.second_event_id);
  await page.goto(`/player/${fixture.player_id}?prop_id=${fixture.prop_id}`);
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
  await page.getByLabel('Research game').selectOption(`event:${fixture.second_event_id}`);
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.other_event_prop_id);
  await page.reload();
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.other_event_prop_id);
});

test('expired offers retain historical research without actionable prices', async ({ page, request }) => {
  const research = await json(request, `/players/${fixture.player_id}/research?prop_id=${fixture.expired_prop_id}`);
  expect(research.selected_prop.actionable).toBe(false);
  expect(research.selected_prop.over_odds).toBeNull();
  expect(research.selected_prop.under_odds).toBeNull();
  expect(research.history.eligible_games).toBeGreaterThan(0);
  await page.goto(`/player/${fixture.player_id}?prop_id=${fixture.expired_prop_id}`);
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.expired_prop_id);
  await expect(page.getByText('Eligible history average')).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.expired_prop_id);
});

test('missing history retains eligible sportsbook odds', async ({ page, request }) => {
  const research = await json(request, `/players/${fixture.missing_history_player_id}/research?prop_id=${fixture.missing_history_prop_id}`);
  expect(research.selected_prop.actionable).toBe(true);
  expect(research.history.eligible_games).toBe(0);
  await page.goto(`/player/${fixture.missing_history_player_id}?prop_id=${fixture.missing_history_prop_id}`);
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.missing_history_prop_id);
  await expect(page.getByText(/No stored game history/).first()).toBeVisible();
  await expect(page.locator('p').filter({ hasText: /FanDuel/ }).first()).toBeVisible();
});

test('empty authoritative Event retains its direct detail page', async ({ page, request }) => {
  const detail = await json(request, `/props/game?event_id=${fixture.empty_event_id}`);
  expect(detail.props).toEqual([]);
  expect(detail.actionable).toBe(false);
  await page.goto(`/games/${fixture.empty_event_id}`);
  await expect(page.getByText('Odds unavailable for this game.')).toBeVisible();
  await page.reload();
  await expect(page.getByText('Odds unavailable for this game.')).toBeVisible();
});

test('Discover and Feed filters use exact Event membership', async ({ page, request }) => {
  const feed = await json(request, `/props/feed?event_id=${fixture.event_id}`);
  expect(feed.props).toHaveLength(10);
  expect(feed.props.every(prop => prop.event_id === fixture.event_id)).toBe(true);
  const responsePromise = page.waitForResponse(response => response.url().includes(`/props/discover?`) && new URL(response.url()).searchParams.get('event_id') === fixture.event_id);
  await page.goto('/discover');
  await page.locator('#discover-game').selectOption(`event:${fixture.event_id}`);
  const response = await responsePromise;
  expect(response.ok()).toBe(true);
  const result = await response.json();
  expect(result.props.length).toBeGreaterThan(0);
  expect(result.props.every(prop => prop.event_id === fixture.event_id)).toBe(true);
  await expect(page.locator('#discover-game')).toHaveValue(`event:${fixture.event_id}`);
});

test('legacy ambiguity and invalid identifiers return safe errors', async ({ page, request }) => {
  const ambiguous = await request.get(`${API}/props/game`, { params: { game_key: fixture.legacy_key } });
  expect(ambiguous.status()).toBe(409);
  await page.goto('/games/' + encodeURIComponent(fixture.legacy_key));
  await expect(page.getByText(/legacy selection is ambiguous/)).toBeVisible();
  await page.goto('/games/not-a-uuid');
  await expect(page.getByText(/game link is malformed/)).toBeVisible();
  await page.goto(`/player/${fixture.player_id}?prop_id=not-a-uuid`);
  await expect(page.getByText('Player research unavailable')).toBeVisible();
  await expect(page).toHaveURL(/prop_id=not-a-uuid$/);
});

test('real minute polling preserves selection', async ({ page }) => {
  await page.clock.install();
  await page.goto(`/player/${fixture.player_id}?prop_id=${fixture.prop_id}`);
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
  const state = observed.get(page);
  const before = state.research.length;
  await page.clock.fastForward(61_000);
  await expect.poll(() => state.research.length).toBeGreaterThan(before);
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
  expect(state.research.every(url => url.searchParams.get('prop_id') === fixture.prop_id)).toBe(true);
});

test('pending real request suppresses overlapping polls and recovers after network failure', async ({ page }) => {
  await page.goto(`/player/${fixture.player_id}?prop_id=${fixture.prop_id}`);
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
  const pattern = `**/players/${fixture.player_id}/research?**`;
  let release;
  let pendingCount = 0;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route(pattern, async route => {
    pendingCount++;
    await gate;
    return route.fallback(); // Actual backend response after controlled network delay.
  });
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect.poll(() => pendingCount).toBe(1);
  await page.evaluate(() => {
    window.dispatchEvent(new Event('online'));
    window.dispatchEvent(new Event('online'));
  });
  // A browser round trip drains the synchronous event handlers while the API is held.
  await page.evaluate(() => document.visibilityState);
  expect(pendingCount).toBe(1);
  const completed = page.waitForResponse(response => response.url().includes(`/players/${fixture.player_id}/research`));
  release();
  expect((await completed).ok()).toBe(true);
  await page.unroute(pattern);
  await expect(page.getByLabel('Research market')).toBeEnabled();
  await page.route('**/props/game?**', route => route.abort('connectionfailed'), { times: 1 });
  await page.goto(`/games/${fixture.event_id}`);
  await expect(page.getByText(/Check your connection/)).toBeVisible();
  await page.getByRole('button', { name: 'Retry game' }).click();
  await expect(page.locator(`a[href="/player/${fixture.player_id}?prop_id=${fixture.prop_id}"]`)).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/games/${fixture.event_id}$`));
});

test('saved and exact slip choices survive navigation and reload without writes', async ({ page, request }) => {
  await page.addInitScript(token => localStorage.setItem('token', token), fixture.token);
  const before = await json(request, '/__test__/snapshot');
  await page.goto(`/games/${fixture.event_id}`);
  await expect(page.getByTitle('Remove bookmark')).toBeVisible();
  await expect(page.getByText('Under 19.5', { exact: true })).toBeVisible();
  await page.locator(`a[href="/player/${fixture.player_id}?prop_id=${fixture.prop_id}"]`).click();
  await expect(page.getByText('Under 19.5', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText('Under 19.5', { exact: true })).toBeVisible();
  const after = await json(request, '/__test__/snapshot');
  expect(after.after).toEqual(before.after);
  expect(after.unchanged).toBe(true);
  expect(after.provider_http_attempts).toBe(0);
});

test('line movement and expiry during actual polling keep the Prop and stored slip', async ({ page, request }) => {
  await page.addInitScript(token => localStorage.setItem('token', token), fixture.token);
  const before = await json(request, '/__test__/snapshot');
  await page.goto(`/player/${fixture.player_id}?prop_id=${fixture.prop_id}`);
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
  try {
    expect((await request.post(`${API}/__test__/scenario`, { data: { scenario: 'moved' } })).ok()).toBe(true);
    await page.evaluate(() => window.dispatchEvent(new Event('online')));
    await expect(page.getByLabel('Research market').locator('option:checked')).toContainText('21.5');
    await expect(page.getByText('Under 19.5', { exact: true })).toBeVisible();
    expect((await request.post(`${API}/__test__/scenario`, { data: { scenario: 'expired' } })).ok()).toBe(true);
    await page.evaluate(() => window.dispatchEvent(new Event('online')));
    await expect(page.getByLabel('Research market').locator('option:checked')).toContainText('Unavailable');
    await expect(page.getByText('Eligible history average')).toBeVisible();
    await expect(page.getByText('Under 19.5', { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
    await expect(page).toHaveURL(new RegExp(`prop_id=${fixture.prop_id}$`));
  } finally {
    expect((await request.post(`${API}/__test__/scenario`, { data: { scenario: 'baseline' } })).ok()).toBe(true);
  }
  const after = await json(request, '/__test__/snapshot');
  expect(after.after).toEqual(before.after);
  expect(after.unchanged).toBe(true);
});


test('rest research defaults to unknown verified participation while recorded history and exact UUID remain independent', async ({ page, request }) => {
  const research = await json(request, `/players/${fixture.player_id}/research?prop_id=${fixture.prop_id}`);
  expect(research.selected_prop.id).toBe(fixture.prop_id);
  expect(research.rest_workload.reference.prop_id).toBe(fixture.prop_id);
  expect(research.rest_workload.verified.status).toBe('unknown');
  expect(research.rest_workload.verified.last_confirmed_appearance).toBeNull();
  expect(research.rest_workload.verified.team_back_to_back).toBeNull();
  expect(research.rest_workload.verified.confirmed_missed_games).toBeNull();
  expect(research.rest_workload.rest).toHaveProperty('games_in_7d');
  await page.goto(`/player/${fixture.player_id}?prop_id=${fixture.prop_id}`);
  await page.getByText('Advanced participation & workload research', { exact: true }).click();
  await expect(page.getByRole('region', { name: 'Player rest', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Team schedule', exact: true })).toBeVisible();
  await expect(page.getByText(/Missing logs do not establish DNP/)).toBeVisible();
  await expect(page.getByText('Recorded appearances: derived rest context')).toBeVisible();
  await expect(page.getByText('Best exact-line odds')).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.prop_id);
  await expect(page).toHaveURL(new RegExp(`prop_id=${fixture.prop_id}$`));
});


test('persisted final-game evidence separates confirmed player rest from team B2B without odds', async ({ page, request }) => {
  const research = await json(request, `/players/${fixture.verified_player_id}/research?prop_id=${fixture.verified_prop_id}`);
  const verified = research.rest_workload.verified;
  expect(verified.status).toBe('confirmed');
  expect(verified.confirmed_missed_games).toBe(2);
  expect(verified.dnp_games).toBe(1); expect(verified.inactive_games).toBe(1);
  expect(verified.last_confirmed_appearance.gap_days).toBe(3);
  expect(verified.last_confirmed_appearance.full_rest_days).toBe(2);
  expect(verified.last_completed_team_game.gap_days).toBe(1);
  expect(verified.team_back_to_back).toBe(true);
  expect(research.selected_prop.actionable).toBe(false);
  expect(research.selected_prop.over_odds).toBeNull();
  expect(research.rest_workload.reference.event_id).toBe(fixture.verified_event_id);
  await page.goto(`/player/${fixture.verified_player_id}?prop_id=${fixture.verified_prop_id}`);
  await page.getByText('Advanced participation & workload research', { exact: true }).click();
  const player = page.getByRole('region', { name: 'Player rest', exact: true });
  const team = page.getByRole('region', { name: 'Team schedule', exact: true });
  await expect(player.getByText('3 / 2 days')).toBeVisible();
  await expect(player.getByText('2 · Confirmed', { exact: true })).toBeVisible();
  await expect(team.getByText('1 / 0 days')).toBeVisible();
  await expect(team.getByText('Yes · Confirmed', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.verified_prop_id);
  await expect(page).toHaveURL(new RegExp(`prop_id=${fixture.verified_prop_id}$`));
});

test('persisted complete schedules support negative team B2B at the exact later Event', async ({ page, request }) => {
  const research = await json(request, `/players/${fixture.verified_player_id}/research?prop_id=${fixture.rested_prop_id}`);
  const verified = research.rest_workload.verified;
  expect(verified.status).toBe('confirmed');
  expect(verified.team_back_to_back).toBe(false);
  expect(verified.confirmed_missed_games).toBe(2);
  expect(verified.last_confirmed_appearance.gap_days).toBe(4);
  expect(verified.last_completed_team_game.gap_days).toBe(2);
  expect(research.rest_workload.reference.event_id).toBe(fixture.rested_event_id);
  await page.goto(`/player/${fixture.verified_player_id}?prop_id=${fixture.rested_prop_id}`);
  await page.getByText('Advanced participation & workload research', { exact: true }).click();
  await expect(page.getByRole('region', { name: 'Player rest', exact: true }).getByText('4 / 3 days')).toBeVisible();
  const team = page.getByRole('region', { name: 'Team schedule', exact: true });
  await expect(team.getByText('2 / 1 days')).toBeVisible();
  await expect(team.getByText('No · Confirmed', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.rested_prop_id);
});

test('persisted partial evidence retains known missed lower bound and separates unknown from uncovered', async ({ page, request }) => {
  const research = await json(request, `/players/${fixture.partial_player_id}/research?prop_id=${fixture.partial_prop_id}`);
  const verified = research.rest_workload.verified;
  expect(verified.status).toBe('partial');
  expect(verified.confirmed_missed_games).toBeNull();
  expect(verified.partial_missed_games_lower_bound).toBe(1);
  expect(verified.unknown_participation_games).toBe(1);
  expect(verified.uncovered_games).toBe(1);
  expect(verified.team_back_to_back).toBeNull();
  expect(research.rest_workload.reference.prop_id).toBe(fixture.partial_prop_id);
  await page.goto(`/player/${fixture.partial_player_id}?prop_id=${fixture.partial_prop_id}`);
  await page.getByText('Advanced participation & workload research', { exact: true }).click();
  await expect(page.getByText('At least 1 · Partial coverage')).toBeVisible();
  await expect(page.getByText(/Unknown participation: 1 games · Uncovered schedule: 1 games/)).toBeVisible();
  await expect(page.getByRole('region', { name: 'Team schedule', exact: true }).getByText('Unknown', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.partial_prop_id);
  const before = await json(request, '/__test__/snapshot');
  await page.reload();
  await expect(page.getByLabel('Research market')).toHaveValue(fixture.partial_prop_id);
  const after = await json(request, '/__test__/snapshot');
  expect(after.after).toEqual(before.after);
  expect(after.unchanged).toBe(true);
  expect(after.provider_http_attempts).toBe(0);
});
