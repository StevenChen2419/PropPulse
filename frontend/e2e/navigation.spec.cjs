const { test, expect } = require('@playwright/test');
const { restWorkload, verifiedRest, nbaVerifiedRest } = require('../tests/fixtures/rest-workload.cjs');

const EVENT = '6ff2324d-5dcb-455b-be37-2ad4dab5370a';
const SECOND_EVENT = '6ff2324d-5dcb-455b-be37-2ad4dab5370b';
const PLAYER = '11111111-1111-4111-8111-111111111111';
const PROP = '22222222-2222-4222-8222-222222222222';
const OTHER_PROP = '22222222-2222-4222-8222-222222222223';
const MARKET_PROP = '22222222-2222-4222-8222-222222222224';
const LEGACY = 'NBA|2099-10-20T19:00:00|Fixture Away|Fixture Home';
const states = new WeakMap();
const context = { event_id: EVENT, identity_source: 'authoritative', sport: 'NBA', provider: 'the_odds_api',
  provider_event_id: 'fixture-only', sport_key: 'basketball_nba', away_team: 'Fixture Away', home_team: 'Fixture Home',
  game_time: '2099-10-20T19:00:00+00:00', scheduled_start_at: '2099-10-20T19:00:00+00:00', game_key: LEGACY };

function fixture() {
  const freshness = { availability: 'available', actionable: true, source: 'live',
    refreshed_at: new Date().toISOString(), provider_observed_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 6 * 3600_000).toISOString() };
  const prop = { ...context, ...freshness, id: PROP,
    player: { id: PLAYER, name: 'Fixture Player', team: 'Traded Team', team_abbr: 'TRADE', sport: 'NBA', age: 27, position: 'G' },
    prop_type: 'points', line: 20.5, sportsbook: 'FanDuel', over_odds: -110, under_odds: -115,
    opponent: 'Stale Opponent', is_home: false, popularity_count: 0, sportsbook_count: 1,
    sportsbook_offers: [{ ...freshness, sportsbook: 'FanDuel', line: 20.5, over_odds: -110, under_odds: -115 }],
    best_over: { sportsbook: 'FanDuel', line: 20.5, odds: -110 }, best_under: { sportsbook: 'FanDuel', line: 20.5, odds: -115 } };
  const other = { ...prop, id: OTHER_PROP, event_id: SECOND_EVENT, game_time: '2099-10-22T19:00:00Z', scheduled_start_at: '2099-10-22T19:00:00Z' };
  const market = { ...prop, id: MARKET_PROP, prop_type: 'assists', line: 5.5 };
  const window = { games: 5, decisions: 5, hits: 3, pushes: 0, hit_rate: .6, seasons: [2026], season_scope: 'previous_seasons' };
  const history = { status: 'available', stored_games: 12, valid_market_games: 12, eligible_games: 12,
    current_season_games: 0, previous_season_games: 12, selected_season: 2099, excluded_counts: {},
    insufficient_l5: false, insufficient_l10: false, competition_scope: 'Provider history excluding preseason; regular season and playoffs are not separately identified.' };
  return { prop, other, market, history, window, empty: false, expired: false, missingHistory: false, gamesMissing: false,
    primaryAlternative: false, errorStatus: 0, hold: null, requests: [], blocked: [],
    games: [{ ...context, ...freshness, prop_count: 1, has_eligible_props: true }],
  };
}

async function setup(page, { authenticated = false } = {}) {
  const state = fixture();
  states.set(page, state);
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin === 'http://127.0.0.1:3199') return route.continue();
    if (!['http://localhost:8000','http://127.0.0.1:8199'].includes(url.origin)) { state.blocked.push(url.origin); return route.abort(); }
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers: {
      'access-control-allow-origin': 'http://127.0.0.1:3199', 'access-control-allow-credentials': 'true', 'access-control-allow-headers': 'Content-Type,X-CSRF-Token', 'access-control-allow-methods': 'GET,POST,DELETE',
    } });
    state.requests.push(url);
    const json = body => route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': 'http://127.0.0.1:3199', 'access-control-allow-credentials': 'true' }, body: JSON.stringify(body) });
    const failure = status => route.fulfill({ status, contentType: 'application/json', headers: { 'access-control-allow-origin': 'http://127.0.0.1:3199', 'access-control-allow-credentials': 'true' }, body: JSON.stringify({ detail: 'Internal fixture detail must not appear' }) });
    if (url.pathname === '/props/todays-games') return json(state.gamesMissing ? [] : state.games);
    if (url.pathname === '/props/feed') return json({ props: [state.prop], total: 1 });
    if (url.pathname === '/props/discover') return state.errorStatus ? failure(state.errorStatus) : json({ props: url.searchParams.get('search') ? [] : state.discoverProps ?? [], total: url.searchParams.get('search') ? 0 : state.discoverProps?.length ?? 0, supported_sports: ['NBA'], filter_options: { sports: ['NBA'], markets: ['points', 'assists'], sportsbooks: ['FanDuel'] } });
    if (url.pathname === '/props/ingestion-status') return json({ source: 'fixture', availability: 'live', current_prop_count: 1 });
    if (url.pathname === '/players/search') return json({ players: [{ ...state.prop.player, live_prop_count: 0, next_game_time: null, top_prop: null }] });
    if (url.pathname === '/props/game') {
      if (state.networkFailure) return route.abort();
      if (state.errorStatus) return failure(state.errorStatus);
      const empty = state.empty || state.expired;
      return json({ ...context, ...state.prop, id: undefined, player: undefined, props: empty ? [] : [state.prop],
        total_props: empty ? 0 : 1, sportsbook_count: empty ? 0 : 1, has_eligible_props: !empty,
        actionable: !empty, availability: empty ? 'market_unavailable' : 'available', source: empty ? 'unavailable' : 'live' });
    }
    if (url.pathname === `/players/${PLAYER}`) return json({ ...state.prop.player, fatigue: state.fatigue || null, props: state.noProps ? [] : [state.prop, state.market, state.other] });
    if (url.pathname === `/players/${PLAYER}/research`) {
      if (state.errorStatus) return failure(state.errorStatus);
      const id = url.searchParams.get('prop_id') || PROP;
      const selected = { ...(id === OTHER_PROP ? state.other : id === MARKET_PROP ? state.market : state.prop) };
      if (state.expired || state.primaryAlternative) Object.assign(selected, { actionable: false, availability: 'expired', source: 'unavailable', over_odds: null, under_odds: null });
      if (state.primaryAlternative) {
        selected.sportsbook_offers = [{ ...state.prop.sportsbook_offers[0], sportsbook: 'DraftKings', over_odds: 120 }];
        selected.best_over = { sportsbook: 'DraftKings', line: selected.line, odds: 120 };
      }
      const response = { player_id: PLAYER, sport: 'NBA', selection_source: 'prop_id', selection_available: selected.actionable,
        selected_prop: selected, available_props: (state.expired ? [state.other, state.market] : [state.prop, state.other, state.market]).map(prop => prop.id === selected.id ? selected : prop),
        rest_workload: state.noWorkload ? undefined : { ...restWorkload(selected.id, selected.event_id), ...(state.workloadOverride || {}) },
        line_movement: null, splits: null, games: state.historyGames ?? [], history: state.missingHistory ? { ...state.history, status: 'no_history', eligible_games: 0 } : state.history,
        trends: state.missingHistory ? null : { line: selected.line, side: 'over', season: 2099, l5: state.window,
          l10: { ...state.window, games: 10, decisions: 10, hits: 6 }, season_window: { ...state.window, games: 0, decisions: 0, hits: 0, hit_rate: null, seasons: [], season_scope: 'empty' }, average: 22, median: 21, recent_games: [] } };
      if (state.noProps) Object.assign(response, { selected_prop: null, available_props: [], trends: null, rest_workload: restWorkload() });
      if (state.summary) response.season_summary = state.summary(url.searchParams.get('season'));
      if (state.hold) { const wait = state.hold; state.hold = null; await wait; }
      try { return await json(response); } catch { return; } // Browser may abort the deliberately delayed request.
    }
    if (url.pathname === '/auth/csrf') return json({csrf_token:'offline-csrf-proof'});
    if (url.pathname === '/users/me') return !authenticated ? failure(401) : json({ id: 'viewer', email: 'fixture@example.invalid', username: 'Fixture researcher', fav_players: [PLAYER], fav_sports: ['NBA'], fav_prop_types: ['points'] });
    if (url.pathname === '/users/me/saved') return json({ saved: [state.prop] });
    if (url.pathname === '/users/me/slip') return json({ slip: { id: 'slip', items: [{ id: 'item', prop_id: PROP, side: 'under',
      selection: { ...state.prop, sportsbook: 'FanDuel', line: 19.5, odds: -115 }, prop: state.prop }] } });
    state.blocked.push(url.pathname);
    return route.abort();
  });
  return state;
}

async function revealSlip(page) {
  const tab = page.getByRole('button', {name:'My Slip'});
  await expect(tab).toBeVisible();
  if (await tab.getAttribute('aria-expanded') === 'false') await tab.click();
}

test.afterEach(async ({ page }) => { expect(states.get(page)?.blocked || []).toEqual([]); });

test('Home -> authoritative Event -> exact Prop research; refresh preserves both URLs', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/');
  const game = page.locator(`a[href="/games/${EVENT}"]`);
  await expect(game).toBeVisible();
  await game.click();
  await expect(page.getByRole('heading', { name: 'Fixture Away @ Fixture Home', exact: true })).toBeVisible();
  expect(state.requests.filter(url => url.pathname === '/props/game').every(url => url.searchParams.get('event_id') === EVENT && !url.searchParams.has('game_key'))).toBeTruthy();
  await page.reload();
  await expect(page.getByRole("link", { name: "Research →", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Research →", exact: true }).click();
  await expect(page.getByLabel('Research market')).toHaveValue(PROP);
  await page.reload();
  await expect(page.getByLabel('Research market')).toHaveValue(PROP);
  await page.screenshot({ path: test.info().outputPath('research.png'), fullPage: true });
  expect(state.blocked).toEqual([]);
});

test('direct Event deep link with zero odds keeps authoritative metadata', async ({ page }) => {
  const state = await setup(page); state.empty = true;
  await page.goto(`/games/${EVENT}`);
  await expect(page.getByRole('heading', { name: 'Fixture Away @ Fixture Home' })).toBeVisible();
  await expect(page.getByText('Odds unavailable for this game.')).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/games/${EVENT}$`));
});

test('legacy ambiguity is explicit and never redirects', async ({ page }) => {
  const state = await setup(page); state.errorStatus = 409;
  await page.goto('/games/' + encodeURIComponent(LEGACY));
  await expect(page.getByText(/legacy selection is ambiguous/)).toBeVisible();
  const request = state.requests.find(url => url.pathname === '/props/game');
  expect(request.searchParams.get('game_key')).toBe(LEGACY);
  expect(request.searchParams.has('event_id')).toBeFalsy();
});

test('generic research pins default; games and markets use exact UUIDs', async ({ page }) => {
  await setup(page);
  await page.goto(`/player/${PLAYER}`);
  await expect(page).toHaveURL(new RegExp(`prop_id=${PROP}$`));
  await expect(page.getByLabel('Research market')).toHaveValue(PROP);
  await page.getByLabel('Research game').selectOption(`event:${SECOND_EVENT}`);
  await expect(page.getByLabel('Research market')).toHaveValue(OTHER_PROP);
  await expect(page).toHaveURL(new RegExp(`prop_id=${OTHER_PROP}$`));
  await page.getByLabel('Research game').selectOption(`event:${EVENT}`);
  await page.getByLabel('Research market').selectOption(MARKET_PROP);
  await expect(page).toHaveURL(new RegExp(`prop_id=${MARKET_PROP}$`));
});

test('polling preserves prop UUID through line movement and expiration with history', async ({ page }) => {
  const state = await setup(page);
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}`);
  await expect(page.getByLabel('Research market')).toHaveValue(PROP);
  state.prop.line = 22.5;
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect(page.getByLabel('Research market').locator('option:checked')).toContainText('22.5');
  state.expired = true;
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect(page.getByLabel('Research market').locator('option:checked')).toContainText('Unavailable');
  await expect(page.getByText('Eligible history average')).toBeVisible();
  await expect(page.getByText(/Previous seasons/).first()).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`prop_id=${PROP}$`));
  expect(state.requests.filter(url => url.pathname.endsWith('/research')).every(url => url.searchParams.get('prop_id') === PROP)).toBeTruthy();
});

test('unavailable primary keeps explicit alternative odds and missing history does not hide odds', async ({ page }) => {
  const state = await setup(page); state.primaryAlternative = true; state.missingHistory = true;
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}`);
  await expect(page.locator('p').filter({ hasText: /FanDuel.*Expired|FanDuel.*unavailable/i }).first()).toBeVisible();
  await expect(page.getByText(/DraftKings.*\+120/).first()).toBeVisible();
  await expect(page.getByText(/No stored game history/).first()).toBeVisible();
});

test('old polling response cannot overwrite a newer research selection', async ({ page }) => {
  const state = await setup(page);
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}`);
  await expect(page.getByLabel('Research market')).toHaveValue(PROP);
  let release;
  state.hold = new Promise(resolve => { release = resolve; });
  const oldRequest = page.waitForRequest(url => url.url().includes('/research'));
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await oldRequest;
  await page.getByLabel('Research market').selectOption(MARKET_PROP);
  await expect(page.getByLabel('Research market')).toHaveValue(MARKET_PROP);
  release();
  await expect(page.getByLabel('Research market')).toHaveValue(MARKET_PROP);
});

test('Discover retains exact Event filter when upcoming list loses its offers', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/discover');
  await page.getByLabel('Discover game', { exact: true }).selectOption(`event:${EVENT}`);
  await expect(page.getByText(/No matching props/)).toBeVisible();
  state.gamesMissing = true;
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await expect(page.getByLabel('Discover game', { exact: true })).toHaveValue(`event:${EVENT}`);
  await expect(page.getByLabel('Discover game', { exact: true }).locator('option:checked')).toContainText('Odds unavailable');
  expect(state.requests.filter(url => url.pathname === '/props/discover' && url.searchParams.has('event_id')).every(url => url.searchParams.get('event_id') === EVENT && !url.searchParams.has('game_key'))).toBeTruthy();
});

test('navigation and deep-link refresh preserve hydrated saved/slip exact choices', async ({ page }) => {
  const state = await setup(page, { authenticated: true });
  await page.goto(`/games/${EVENT}`);
  await expect(page.getByRole('button', { name: 'My Slip' })).toBeVisible();
  await revealSlip(page);
  await expect(page.getByText('Under 19.5', { exact: true })).toBeVisible();
  await expect(page.getByTitle('Remove bookmark')).toBeVisible();
  await page.getByRole('button', {name:'My Slip'}).click();
  await page.getByRole("link", { name: "Research →", exact: true }).click();
  await revealSlip(page);
  await expect(page.getByText('Under 19.5', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Following' })).toBeVisible();
  await page.reload();
  await revealSlip(page);
  await expect(page.getByText('Under 19.5', { exact: true })).toBeVisible();
  expect(state.blocked).toEqual([]);
});

for (const status of [400, 404, 422]) test(`invalid identity ${status} shows a safe error without another selection`, async ({ page }) => {
  const state = await setup(page); state.errorStatus = status;
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}`);
  await expect(page.getByText('Player research unavailable')).toBeVisible();
  await expect(page.getByText(/Internal fixture detail/)).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`prop_id=${PROP}$`));
});

for (const status of [404, 422]) test(`Event error ${status} preserves the requested URL`, async ({ page }) => {
  const state = await setup(page); state.errorStatus = status;
  await page.goto(`/games/${EVENT}`);
  await expect(page.getByText(status === 404 ? /game could not be found/ : /game link is malformed/)).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/games/${EVENT}$`));
});

test('network failure is retryable without selecting another Event', async ({ page }) => {
  const state = await setup(page); state.networkFailure = true;
  await page.goto(`/games/${EVENT}`);
  await expect(page.getByText(/Check your connection/)).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/games/${EVENT}$`));
  state.networkFailure = false;
  await page.getByRole('button', { name: 'Retry game' }).click();
  await expect(page.getByRole('heading', { name: 'Fixture Away @ Fixture Home' })).toBeVisible();
});

test('unambiguous legacy link remains usable and explicitly unverified', async ({ page }) => {
  const state = await setup(page);
  Object.assign(state.prop, { event_id: null, identity_source: 'legacy', provider: null });
  await page.goto('/games/' + encodeURIComponent(LEGACY));
  await expect(page.getByText(/Legacy.*unverified/).first()).toBeVisible();
  expect(state.requests.find(url => url.pathname === '/props/game').searchParams.get('game_key')).toBe(LEGACY);
});

test('minute timer refresh keeps the URL-backed research UUID', async ({ page }) => {
  const state = await setup(page);
  await page.clock.install();
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}`);
  await expect(page.getByLabel('Research market')).toHaveValue(PROP);
  state.prop.line = 23.5;
  await page.clock.fastForward(61_000);
  await expect(page.getByLabel('Research market').locator('option:checked')).toContainText('23.5');
  await expect(page).toHaveURL(new RegExp(`prop_id=${PROP}$`));
});

test('legacy URL decoding preserves literal percent escapes in the key', async ({ page }) => {
  const state = await setup(page);
  const key = LEGACY.replace('Fixture Away', 'Fixture%20Away');
  await page.goto('/games/' + encodeURIComponent(key));
  await expect(page.getByRole('heading', { name: 'Fixture Away @ Fixture Home' })).toBeVisible();
  expect(state.requests.find(url => url.pathname === '/props/game').searchParams.get('game_key')).toBe(key);
});


test('rest workload remains independent of expired odds, missing market history and selected UUID', async ({ page }) => {
  const state = await setup(page); state.expired = true; state.missingHistory = true;
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}`);
  const section = page.getByRole('region', { name: 'Rest & Workload' });
  await expect(section).toBeVisible();
  await expect(section.getByText('Observed minutes')).toBeVisible();
  await expect(section.getByText('Schedule coverage is incomplete.', { exact: false })).toBeVisible();
  await section.getByText('Data coverage & calculation details').click();
  await expect(section.getByText(/10 eligible of 13 stored games/)).toBeVisible();
  await expect(page.getByText(/No stored game history/).first()).toBeVisible();
  await expect(page.getByLabel('Research market')).toHaveValue(PROP);
  await page.reload();
  await expect(section).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`prop_id=${PROP}$`));
  expect(state.requests.filter(url => url.pathname.endsWith('/research')).every(url => url.searchParams.get('prop_id') === PROP)).toBeTruthy();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test('older research response keeps odds and history without workload', async ({ page }) => {
  const state = await setup(page); state.noWorkload = true;
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}`);
  await expect(page.getByText('Eligible history average')).toBeVisible();
  await expect(page.getByText('Best exact-line odds')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Rest & Workload' })).toHaveCount(0);
});


test('player with no current props still has workload research', async ({ page }) => {
  const state = await setup(page); state.noProps = true;
  await page.goto(`/player/${PLAYER}`);
  await expect(page.getByText('No current sportsbook-backed props for this player')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Rest & Workload' })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/player/${PLAYER}$`));
});

test('legacy fatigue stays explicitly experimental without injury or betting claims', async ({ page }) => {
  const state = await setup(page);
  state.fatigue = { fatigue_score: .8123, fatigue_label: 'High', shap_reasons: ['Guaranteed performance decline'], risk_flags: [], rolling_minutes_7d: 40 };
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}`);
  const disclosure = page.getByText('Experimental fatigue estimate', { exact: true });
  await expect(disclosure).toBeVisible(); await disclosure.click();
  await expect(page.getByText(/Legacy score: 0.812 on a 0–1 scale/)).toBeVisible();
  await expect(page.getByText('Guaranteed performance decline')).toHaveCount(0);
  await expect(page.getByText('High Risk', { exact: true })).toHaveCount(0);
});


test('verified player rest differs from confirmed team back-to-back without changing exact Prop selection', async ({ page }) => {
  const state = await setup(page); state.workloadOverride = { verified: verifiedRest() };
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}`);
  const player = page.getByRole('region', { name: 'Player rest', exact: true });
  const team = page.getByRole('region', { name: 'Team schedule', exact: true });
  await expect(player.getByText('3 / 2 days')).toBeVisible();
  await expect(player.getByText('1 · Confirmed', { exact: true })).toBeVisible();
  await expect(team.getByText('1 / 0 days')).toBeVisible();
  await expect(team.getByText('Yes · Confirmed', { exact: true })).toBeVisible();
  await expect(page.getByText('Recorded appearances: derived rest context')).toBeVisible();
  await expect(page.getByLabel('Research market')).toHaveValue(PROP);
  await page.reload();
  await expect(player).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`prop_id=${PROP}$`));
});

test('partial participation and schedule keep lower bounds separate from unknown team status', async ({ page }) => {
  const state = await setup(page); state.workloadOverride = { verified: verifiedRest({ status: 'partial', confirmed_missed_games: null,
    team_back_to_back: null, unknown_participation_games: 2, uncovered_games: 3, schedule_complete: false }) };
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}`);
  await expect(page.getByText('At least 1 · Partial coverage')).toBeVisible();
  await expect(page.getByText(/Unknown participation: 2 games · Uncovered schedule: 3 games/)).toBeVisible();
  const team = page.getByRole('region', { name: 'Team schedule', exact: true });
  await expect(team.getByText('Unknown', { exact: true })).toBeVisible();
  await expect(team.getByText('No · Confirmed')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test('NBA.com rest evidence displays provenance and unknown missed games while preserving selected Prop', async ({ page }) => {
  const state = await setup(page); state.workloadOverride = { verified: nbaVerifiedRest() };
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}`);
  const player = page.getByRole('region', { name: 'Player rest', exact: true });
  await expect(player.getByText('3 / 2 days')).toBeVisible();
  await expect(player.getByText('Unknown', { exact: true })).toBeVisible();
  const team = page.getByRole('region', { name: 'Team schedule', exact: true });
  await expect(team.getByText('Unknown', { exact: true })).toHaveCount(3);
  await page.getByText('Participation evidence & coverage', { exact: true }).click();
  await expect(page.getByText('Sources: NBA.com PlayerGameLog, NBA.com LeagueGameLog', { exact: true })).toBeVisible();
  await expect(player.getByText('Eastern calendar date only; actual game time unavailable.', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Research market')).toHaveValue(PROP);
  await page.reload();
  await expect(page.getByLabel('Research market')).toHaveValue(PROP);
  await expect(page).toHaveURL(new RegExp(`prop_id=${PROP}$`));
});

test('missing verified evidence leaves player and team facts unknown without treating missing logs as zero', async ({ page }) => {
  await setup(page);
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}`);
  const player = page.getByRole('region', { name: 'Player rest', exact: true });
  await expect(player.getByText('Unknown', { exact: true })).toHaveCount(3);
  await expect(page.getByText(/Missing logs do not establish DNP/)).toBeVisible();
  await expect(page.getByText('0 · Confirmed', { exact: true })).toHaveCount(0);
});


test('uppercase Prop UUID preserves the URL while canonical research and workload remain visible', async ({ page }) => {
  const canonical = 'abcdefab-cdef-4abc-8def-abcdefabcdef';
  const requested = canonical.toUpperCase();
  const state = await setup(page);
  state.prop.id = canonical;
  const response = page.waitForResponse(item => item.url().includes(`/players/${PLAYER}/research`));
  await page.goto(`/player/${PLAYER}?prop_id=${requested}`);
  const research = await (await response).json();
  expect(research.selected_prop.id).toBe(canonical);
  expect(research.rest_workload.reference.prop_id).toBe(canonical);
  await expect(page.getByLabel('Research market')).toHaveValue(canonical);
  await expect(page.getByRole('region', { name: 'Rest & Workload' })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`prop_id=${requested}$`));
  await page.reload();
  await expect(page.getByLabel('Research market')).toHaveValue(canonical);
  await expect(page.getByRole('region', { name: 'Rest & Workload' })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`prop_id=${requested}$`));
  expect(state.requests.filter(url => url.pathname.endsWith('/research')).every(url => url.searchParams.get('prop_id') === requested)).toBeTruthy();
});

// Invented offline fixtures; no provider or database access.
test('NBA season selection preserves exact Prop, competition, reload and player navigation', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-10-24T16:00:00Z'));
  const state = await setup(page);
  const metric = { average: 14, valid_samples: 2 };
  const window = { appearances: 2, points: metric, rebounds: metric, assists: metric, minutes: metric };
  state.summary = season => ({
    status: season ? 'available' : 'unavailable', season: season || '2026-27', competition: 'Regular Season',
    source: season ? 'nba_com_stats' : null, recorded_appearances: season ? 2 : 0,
    coverage_start: '2026-01-01', coverage_end: '2026-01-03', latest_appearance: '2026-01-03',
    last_observed_at: null, reference_date: '2026-01-04', calendar_day_gap: 1, full_intervening_days: 0,
    date_precision: 'eastern_date', l5: window, l10: window, notes: ['Invented offline fixture.'],
  });
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}&competition=Regular+Season`);
  const summary = page.getByRole('region', { name: 'Season statistics' });
  await expect(summary).toContainText('No NBA.com appearances recorded');
  await expect(summary).toContainText('Source unavailable');
  await expect(page.getByText(/Line-based charts and splits below use separate ESPN history/)).toBeVisible();
  await page.getByLabel('NBA statistics season').selectOption('2025-26');
  await expect(summary).toContainText('Historical Performance');
  await expect(summary).toContainText('2 appearances');
  expect(new URL(page.url()).searchParams.get('prop_id')).toBe(PROP);
  expect(new URL(page.url()).searchParams.get('competition')).toBe('Regular Season');
  await page.reload();
  await expect(page.getByLabel('NBA statistics season')).toHaveValue('2025-26');
  await page.getByLabel('Research market').selectOption(MARKET_PROP);
  await expect(page.getByLabel('Research market')).toHaveValue(MARKET_PROP);
  expect(new URL(page.url()).searchParams.get('season')).toBe('2025-26');
  await page.getByRole('link', { name: 'Research another player with this season scope' }).click();
  await page.getByRole('link', { name: /Fixture Player NBA/ }).click();
  await expect(page.getByLabel('NBA statistics season')).toHaveValue('2025-26');
  await page.getByLabel('NBA statistics season').selectOption('2026-27');
  await expect(summary).toContainText('Recent Performance');
  await expect(summary).toContainText('2/2 valid');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

// UI fixtures are invented and isolated; no application records or providers are touched.
for (const width of [375, 430, 768, 1280, 1440, 1920]) test(`workspace layouts and controls at ${width}px`, async ({ page }, info) => {
  const state = await setup(page, { authenticated: true });
  state.discoverProps = [state.prop, state.market];
  await page.setViewportSize({ width, height: 900 });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  for (const path of ['/discover', '/players', '/saved', '/profile', '/login', `/games/${EVENT}`]) {
    await page.goto(path);
    await expect(page.locator('h1')).toBeVisible();
    if (path !== '/login') await expect(page.locator('.animate-pulse')).toHaveCount(0);
    // Collapse the persisted slip to inspect the workspace and avoid obscuring actions.
    const tab = page.getByRole('button', { name: 'My Slip' });
    if (await tab.isVisible() && await tab.getAttribute('aria-expanded') === 'true') await tab.click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (path === '/discover') {
      const search = page.getByRole('searchbox', { name: 'Search Discover props' });
      await search.fill('does not exist');
      await expect(page.getByRole('heading', { name: 'No matching props' })).toBeVisible();
      await search.fill('');
      await expect(search).toHaveValue('');
      await page.getByLabel('Prop market filter').selectOption('points');
      await expect.poll(() => state.requests.filter(url => url.pathname === '/props/discover').at(-1).searchParams.get('prop_type')).toBe('points');
    }
    if (width === 375 || width === 1440) await page.screenshot({ path: info.outputPath(`ui-${path.split('/')[1]}-${width}.png`), fullPage: true });
  }
  await page.goto('/discover');
  if (width < 1280) {
    const menu = page.locator('button[aria-controls="mobile-navigation"]');
    await menu.click(); await expect(menu).toHaveAttribute('aria-expanded', 'true');
    if(width === 375) await page.screenshot({path:info.outputPath('mobile-navigation.png'),fullPage:true});
    await page.keyboard.press('Escape'); await expect(menu).toBeFocused();
    await menu.click();
  }
  await page.getByRole('button', { name: 'Research slip', exact: true }).click();
  await expect(page.getByRole('button', { name: 'My Slip' })).toHaveAttribute('aria-expanded', 'true');
  await revealSlip(page);
  await expect(page.getByText('Under 19.5', { exact: true })).toBeVisible();
  if(width === 375 || width === 1440) await page.screenshot({path:info.outputPath(`open-slip-${width}.png`),fullPage:true});
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'My Slip' })).toHaveAttribute('aria-expanded', 'false');
  expect(errors).toEqual([]);
});

test('Discover error can retry; loading and empty slip communicate state', async ({ page }) => {
  const state = await setup(page); state.errorStatus = 503;
  await page.goto('/discover');
  await expect(page.locator('main').getByRole('alert')).toBeVisible();
  await expect(page.locator('main').getByRole('alert')).not.toContainText('Internal fixture detail');
  await page.screenshot({ path: test.info().outputPath('discover-error.png'), fullPage: true });
  state.errorStatus = 0;
  await page.getByRole('button', { name: 'Try again', exact: true }).click();
  await expect(page.getByText(/No matching props/)).toBeVisible();
  if (await page.getByRole('button', { name: 'Open navigation' }).isVisible()) await page.getByRole('button', { name: 'Open navigation' }).click();
  await page.getByRole('button', { name: 'Research slip', exact: true }).click();
  await expect(page.getByText('Your research slip is empty')).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('empty-slip.png'), fullPage: true });
  await page.getByRole('button', { name: 'My Slip' }).click();
  let release;
  await page.route('**/props/discover?**', async route => {
    await new Promise(resolve => { release = resolve; });
    await route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': 'http://127.0.0.1:3199', 'access-control-allow-credentials': 'true' }, body: JSON.stringify({ props: [], total: 0 }) });
  });
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.locator('.animate-pulse')).toHaveCount(1);
  await expect.poll(() => typeof release).toBe('function');
  await page.screenshot({ path: test.info().outputPath('discover-loading.png'), fullPage: true });
  release(); await expect(page.locator('.animate-pulse')).toHaveCount(0);
});

test('failed bookmark removal rolls back and announces failure', async ({ page }) => {
  await setup(page, { authenticated: true });
  await page.route(`**/interactions/${PROP}/save`, route => route.fulfill({ status: 503, contentType: 'application/json', headers: { 'access-control-allow-origin': 'http://127.0.0.1:3199', 'access-control-allow-credentials': 'true' }, body: JSON.stringify({ detail: 'Fixture failure' }) }));
  await page.goto('/saved');
  await page.getByTitle('Remove bookmark').click();
  await expect(page.locator('main').getByRole('alert')).toContainText('Could not remove your bookmark');
  await expect(page.getByTitle('Remove bookmark')).toBeVisible();
});

test('login labels, native validation and rejected sign-in stay usable', async ({ page }) => {
  await setup(page);
  await page.route('**/auth/login', route => route.fulfill({ status: route.request().method() === 'OPTIONS' ? 204 : 401, contentType: 'application/json', headers: { 'access-control-allow-origin': 'http://127.0.0.1:3199', 'access-control-allow-credentials': 'true', 'access-control-allow-headers': 'Content-Type,X-CSRF-Token', 'access-control-allow-methods': 'POST,OPTIONS' }, body: route.request().method() === 'OPTIONS' ? undefined : JSON.stringify({ detail: 'Incorrect email or password.' }) }));
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill('bad-email');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  expect(await page.getByLabel('Email', { exact: true }).evaluate(input => input.validity.valid)).toBe(false);
  await page.getByLabel('Email', { exact: true }).fill('fixture@example.invalid');
  await page.getByLabel('Password', { exact: true }).fill('invented-test-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.locator('main').getByRole('alert')).toHaveText('Incorrect email or password.');
  await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeEnabled();
});

test('populated research chart, historical summary and empty current season render independently', async ({ page }) => {
  const state = await setup(page);
  state.historyGames = Array.from({length: 10}, (_, index) => ({ game_date: `2026-01-${String(index + 1).padStart(2, '0')}`, opponent: 'Fixture opponent', is_home: index % 2 === 0, value: 18 + index, result: index > 2 ? 'hit' : 'miss' }));
  const metric = { average: 24, valid_samples: 5 };
  const window = { appearances: 5, points: metric, rebounds: { average: 7, valid_samples: 5 }, assists: { average: 8, valid_samples: 5 }, minutes: { average: 32, valid_samples: 5 } };
  state.summary = season => ({ status: season === '2025-26' ? 'available' : 'unavailable', season: season || '2026-27', competition: 'Regular Season', source: season === '2025-26' ? 'nba_com_stats' : null, recorded_appearances: season === '2025-26' ? 10 : 0, l5: window, l10: { ...window, appearances: 10 }, latest_appearance: '2026-01-10', coverage_start: '2026-01-01', coverage_end: '2026-01-10', last_observed_at: null, reference_date: '2026-10-19', calendar_day_gap: 282, full_intervening_days: 281, notes: ['Invented offline UI fixture.'], date_precision: 'eastern_date' });
  for (const width of [375, 768, 1440]) {
    await page.setViewportSize({width, height: 900});
    await page.goto(`/player/${PLAYER}?prop_id=${PROP}&season=2025-26`);
    await expect(page.getByRole('region', { name: 'Season statistics' })).toContainText('Historical Performance');
    await expect(page.locator('.recharts-wrapper')).toBeVisible();
    await expect(page.getByRole('group', {name:'Historical result legend'}).getByText('hit', {exact:true})).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({path:test.info().outputPath(`chart-history-${width}.png`), fullPage:true});
    await page.getByLabel('NBA statistics season').selectOption('2026-27');
    await expect(page.getByRole('region', {name:'Season statistics'})).toContainText('No NBA.com appearances recorded');
    await expect(page.locator('.recharts-wrapper')).toBeVisible();
    await expect(page.getByLabel('Research market')).toHaveValue(PROP);
    await page.screenshot({path:test.info().outputPath(`empty-current-${width}.png`),fullPage:true});
  }
});

test('save and slip actions preserve selected side, sportsbook and line after reload', async ({ page }) => {
  const state = await setup(page, {authenticated:true}); state.discoverProps = [state.prop];
  let saved = false, pick = null; const mutations = [];
  const respond = (route, body) => route.fulfill({status:route.request().method() === 'OPTIONS' ? 204 : 200, contentType:'application/json', headers:{'access-control-allow-origin':'http://127.0.0.1:3199','access-control-allow-credentials':'true','access-control-allow-headers':'Content-Type,X-CSRF-Token','access-control-allow-methods':'GET,POST,DELETE,OPTIONS'}, body:route.request().method() === 'OPTIONS' ? undefined : JSON.stringify(body)});
  await page.route('**/users/me/saved', route => respond(route, {saved:saved ? [state.prop] : []}));
  await page.route('**/users/me/slip', route => respond(route, {slip:{id:'fixture-slip',items:pick ? [{id:'fixture-pick',prop:state.prop,prop_id:PROP,side:pick.side,selection:{...state.prop.sportsbook_offers[0],odds:-115,line:pick.line}}] : []}}));
  await page.route(`**/interactions/${PROP}`, route => {
    if (route.request().method() === 'OPTIONS') return respond(route, {});
    const body = route.request().postDataJSON(); mutations.push(body);
    if (body.action === 'save') saved = true;
    if (body.action === 'add_to_slip') pick = body;
    return respond(route, {ok:true,action:body.action});
  });
  await page.goto('/discover');
  await page.getByTitle('Save for later').click();
  await expect(page.getByTitle('Remove bookmark')).toHaveAttribute('aria-pressed','true');
  await page.getByRole('group',{name:'Choose a side for Fixture Player'}).getByRole('button').filter({hasText:'under'}).click();
  await page.getByRole('button',{name:'Add Under to Slip',exact:true}).click();
  await revealSlip(page);
  await expect(page.getByText('Under 20.5',{exact:true})).toBeVisible();
  expect(mutations).toContainEqual({action:'add_to_slip',side:'under',sportsbook:'FanDuel',line:20.5});
  await page.reload();
  await expect(page.getByTitle('Remove bookmark')).toHaveAttribute('aria-pressed','true');
  await revealSlip(page);
  await expect(page.getByText('Under 20.5',{exact:true})).toBeVisible();
  expect(pick.side).toBe('under'); expect(pick.sportsbook).toBe('FanDuel'); expect(pick.line).toBe(20.5);
});

test('unavailable saved book and line stay visible until an explicit alternative is selected', async ({ page }) => {
  await setup(page, { authenticated: true });
  await page.goto('/saved');
  const book = page.getByLabel('Sportsbook for Fixture Player under');
  await expect(book).toHaveValue(JSON.stringify(['FanDuel',19.5]));
  await expect(book.locator('option:checked')).toHaveText('FanDuel · Under 19.5 · Unavailable (saved selection)');
  const sides = page.getByRole('group', {name:'Choose a side for Fixture Player'});
  await expect(sides.getByRole('button').filter({hasText:'under'})).toBeDisabled();
  await expect(sides.getByRole('button').filter({hasText:'under'})).toContainText('19.5');
  await expect(sides.getByRole('button').filter({hasText:'over'})).toBeEnabled();
  const tab = page.getByRole('button', {name:'My Slip'});
  if(await tab.getAttribute('aria-expanded') === 'true') await tab.click();
  await book.selectOption(JSON.stringify(['FanDuel',20.5]));
  await expect(sides.getByRole('button').filter({hasText:'under'})).toBeEnabled();
  await expect(sides.getByRole('button').filter({hasText:'under'})).toContainText('20.5');
  await tab.click();
  await expect(page.getByText('Under 19.5',{exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Sportsbook for Fixture Player under')).toHaveValue(JSON.stringify(['FanDuel',19.5]));
});

test('explicit side switches select the displayed offer and leave the stored pick intact', async ({ page }) => {
  await setup(page, {authenticated:true});
  await page.goto('/saved');
  const sides = page.getByRole('group',{name:'Choose a side for Fixture Player'});
  const tab = page.getByRole('button',{name:'My Slip'});
  if(await tab.getAttribute('aria-expanded') === 'true') await tab.click();
  await expect(sides.getByRole('button').filter({hasText:'under'})).toContainText('19.5');
  await sides.getByRole('button').filter({hasText:'over'}).click();
  await expect(page.getByLabel('Sportsbook for Fixture Player over')).toHaveValue(JSON.stringify(['FanDuel',20.5]));
  await expect(sides.getByRole('button').filter({hasText:'under'})).toContainText('20.5');
  await sides.getByRole('button').filter({hasText:'under'}).click();
  await expect(page.getByLabel('Sportsbook for Fixture Player under')).toHaveValue(JSON.stringify(['FanDuel',20.5]));
  await revealSlip(page);
  await expect(page.getByText('Under 19.5',{exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Sportsbook for Fixture Player under')).toHaveValue(JSON.stringify(['FanDuel',19.5]));
});
