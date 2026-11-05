const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');

function load(relative, mocks) {
  const filename = path.resolve(__dirname, '../src', relative);
  const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    fileName: filename,
  }).outputText;
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const native = mod.require.bind(mod);
  mod.require = name => {
    if (name in mocks) return mocks[name];
    if (name.startsWith('@/')) {
      const target = name.slice(2);
      return load(target + (fs.existsSync(path.resolve(__dirname, '../src', target + '.ts')) ? '.ts' : '.tsx'), mocks);
    }
    if (name === "./ResearchHistorySummary") return load("components/ResearchHistorySummary.tsx", mocks);
    return native(name);
  };
  mod._compile(compiled, filename);
  return mod.exports;
}
const flush = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const prop = (id, event = 'event-a', changes = {}) => ({
  id, event_id: event, identity_source: 'authoritative', home_team: 'Detroit Pistons', away_team: 'Boston Celtics',
  scheduled_start_at: '2099-10-20T19:00:00+00:00', game_time: '2099-10-20T19:00:00+00:00',
  prop_type: 'points', line: 20.5, sportsbook: 'FanDuel', sportsbook_count: 1,
  availability: 'available', actionable: true, expires_at: '2099-10-20T18:00:00Z',
  provider_observed_at: new Date().toISOString(),
  over_odds: -110, under_odds: -105, ...changes,
});
const research = (selected, available = [selected]) => ({ selected_prop: selected, available_props: available,
  trends: null, games: [], splits: null, line_movement: null, history: { status: 'no_history', eligible_games: 0, excluded_counts: {} } });
function nodes(tree, type) {
  if (tree == null || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(item => nodes(item, type));
  return [...(tree.type === type ? [tree] : []), ...nodes(tree.props?.children, type)];
}
function harness(initialProp, handler, playerHandler, scope = {}) {
  let playerId = "player";
  let query = new URLSearchParams({ ...scope, ...(initialProp ? { prop_id: initialProp } : {}) }), index = 0, pending = [], tree, polling;
  const slots = [], calls = [], navigation = [];
  const router = { push: url => navigation.push(['push', url]), replace: url => navigation.push(['replace', url]), back() {} };
  const api = {
    getPlayer: async (id) => playerHandler ? playerHandler(id) : ({ id, name: `Player ${id}`, team: 'Changed Team', sport: 'NBA', props: [] }),
    getMe: async () => null,
    getPlayerResearch: (id, params, signal) => { calls.push({ id, params, signal }); return handler(params, calls.length); },
  };
  const hooks = {
    ...React,
    useState(initial) { const key = index++; if (!(key in slots)) slots[key] = typeof initial === 'function' ? initial() : initial; return [slots[key], value => { slots[key] = typeof value === 'function' ? value(slots[key]) : value; }]; },
    useRef(initial) { const key = index++; if (!(key in slots)) slots[key] = { current: initial }; return slots[key]; },
    useMemo: fn => fn(),
    useCallback: fn => fn,
    useEffect(fn, deps) { const key = index++; const previous = slots[key]; if (!previous || deps.some((value, n) => value !== previous.deps[n])) { pending.push(() => { previous?.cleanup?.(); slots[key] = { deps, cleanup: fn() }; }); } },
  };
  const Page = load('app/player/[id]/page.tsx', {
    react: hooks,
    'next/link': 'a',
    'next/navigation': { useParams: () => ({ id: playerId }), useSearchParams: () => query, useRouter: () => router },
    '@/lib/api': { api }, '@/lib/useOfferClock': { useOfferClock() {} },
    '@/lib/useLiveRefresh': { useLiveRefresh(fn) { polling = fn; } },
  }).default;
  return {
    calls, navigation,
    render(commit = false) { index = 0; pending = []; const wrapper = Page(); tree = wrapper.props.children.type(); if (commit) pending.forEach(fn => fn()); return tree; },
    navigate(value) { query = new URLSearchParams(value ? { prop_id: value } : {}); },
    navigateQuery(value) { query = new URLSearchParams(value); },
    navigatePlayer(value, propValue) { playerId = value; query = new URLSearchParams(propValue ? { prop_id: propValue } : {}); },
    poll: () => polling(),
    cleanup() { for (const value of slots) value?.cleanup?.(); },
    tree: () => tree,
  };
}

test('historical scope reaches research and survives default pinning and market navigation', async () => {
  const scope = { season: '2025-26', competition: 'Regular Season' };
  const app = harness(null, async () => research(prop('first'), [prop('first'), prop('second')]), undefined, scope);
  app.render(true); await flush(); app.render();
  assert.deepEqual(app.calls[0].params, scope);
  assert.deepEqual(app.navigation[0], ['replace', '/player/player?prop_id=first&season=2025-26&competition=Regular+Season']);
  const market = nodes(app.tree(), 'select').find(node => node.props['aria-label'] === 'Research market');
  market.props.onChange({ target: { value: 'second' } });
  assert.deepEqual(app.navigation.at(-1), ['push', '/player/player?prop_id=second&season=2025-26&competition=Regular+Season']);
  const season = nodes(app.tree(), 'select').find(node => node.props['aria-label'] === 'NBA statistics season');
  season.props.onChange({ target: { value: '2026-27' } });
  assert.deepEqual(app.navigation.at(-1), ['push', '/player/player?season=2026-27&competition=Regular+Season']);
  app.cleanup();
});

test('scope navigation aborts old requests and hides old statistics until the new season resolves', async () => {
  const next = deferred();
  const app = harness('pinned', params => params.season === '2025-26'
    ? Promise.resolve({ ...research(prop('pinned')), season_summary: { notes: ['old season marker'] } })
    : next.promise, undefined, { season: '2025-26', competition: 'Regular Season' });
  app.render(true); await flush(); app.render();
  assert.match(JSON.stringify(app.tree()), /old season marker/);
  app.navigateQuery({ prop_id: 'pinned', season: '2026-27', competition: 'Regular Season' });
  app.render(true); await flush(); app.render();
  assert.equal(app.calls[0].signal.aborted, true);
  assert.deepEqual(app.calls[1].params, { prop_id: 'pinned', season: '2026-27', competition: 'Regular Season' });
  assert.doesNotMatch(JSON.stringify(app.tree()), /old season marker/);
  next.resolve({ ...research(prop('pinned')), season_summary: { notes: ['new season marker'] } });
  await flush(); app.render();
  assert.match(JSON.stringify(app.tree()), /new season marker/);
  app.cleanup();
});

test('explicit and default NBA summary scope distinguish independently scoped legacy ESPN charts', async () => {
  const result = { ...research(prop('pinned')), season_summary: {
    season: '2025-26', competition: 'Regular Season', source: 'nba_com_stats',
  } };
  const app = harness('pinned', async () => result, undefined,
    { season: '2025-26', competition: 'Regular Season' });
  app.render(true); await flush(); app.render();
  const notice = nodes(app.tree(), 'p').find(node => JSON.stringify(node.props.children).includes('Season summary above:'));
  assert.ok(notice);
  assert.match(JSON.stringify(notice.props.children), /2025-26/);
  assert.match(JSON.stringify(notice.props.children), /Regular Season/);
  assert.match(JSON.stringify(notice.props.children), /separate ESPN history/);
  assert.match(JSON.stringify(notice.props.children), /summary filters do not apply/);
  assert.equal(nodes(app.tree(), 'select').find(node => node.props['aria-label'] === 'Research market').props.value, 'pinned');
  app.cleanup();

  const defaultScope = harness('pinned', async () => result);
  defaultScope.render(true); await flush(); defaultScope.render();
  assert.match(JSON.stringify(defaultScope.tree()), /separate ESPN history/);
  const season = nodes(defaultScope.tree(), 'select').find(node => node.props['aria-label'] === 'NBA statistics season');
  season.props.onChange({ target: { value: '2026-27' } });
  assert.deepEqual(defaultScope.navigation.at(-1), ['push', '/player/player?prop_id=pinned&season=2026-27']);
  defaultScope.cleanup();

  const playerOnly = harness(null, async () => ({ ...result, selected_prop: null, available_props: [] }), undefined,
    { season: '2025-26', competition: 'Regular Season' });
  playerOnly.render(true); await flush(); playerOnly.render();
  assert.doesNotMatch(JSON.stringify(playerOnly.tree()), /separate ESPN history/);
  playerOnly.cleanup();
});

test('generic research pins backend default in URL, then polls exact UUID across line movement', async () => {
  let selected = prop('prop-a');
  const app = harness(null, async () => research(selected));
  app.render(true); await flush();
  assert.deepEqual(app.calls[0].params, undefined);
  assert.deepEqual(app.navigation[0], ['replace', '/player/player?prop_id=prop-a']);
  selected = prop('prop-a', 'event-a', { line: 23.5 });
  await app.poll();
  assert.deepEqual(app.calls[1].params, { prop_id: 'prop-a' });
  app.navigate('prop-a'); app.render();
  assert.equal(nodes(app.tree(), 'select').find(node => node.props['aria-label'] === 'Research market').props.value, 'prop-a');
  assert.ok(app.calls.every(call => !call.params || !('line' in call.params) && !('prop_type' in call.params)));
  app.cleanup();
});

test('game and market options retain unavailable selected UUID and separate duplicate markets by Event', async () => {
  const selected = prop('old', 'event-a', { availability: 'expired', actionable: false, over_odds: null, under_odds: null });
  const later = prop('later', 'event-b', { scheduled_start_at: '2099-10-22T19:00:00Z' });
  const app = harness('old', async () => research(selected, [later]));
  app.render(true); await flush(); app.render();
  const selects = nodes(app.tree(), 'select');
  const games = selects.find(node => node.props['aria-label'] === 'Research game');
  const markets = selects.find(node => node.props['aria-label'] === 'Research market');
  assert.equal(games.props.value, 'event:event-a');
  assert.equal(nodes(games, 'option').length, 2);
  assert.equal(markets.props.value, 'old');
  assert.equal(nodes(markets, 'option')[0].props.value, 'old');
  assert.match(JSON.stringify(nodes(markets, 'option')[0].props.children), /Unavailable/);
  games.props.onChange({ target: { value: 'event:event-b' } });
  assert.deepEqual(app.navigation.at(-1), ['push', '/player/player?prop_id=later']);
  assert.equal(app.calls[0].signal.aborted, true);
  app.cleanup();
});

test('navigation rejects stale response and stale errors even if transport ignores abort', async () => {
  const old = deferred(), current = deferred();
  const app = harness('old', params => params.prop_id === 'old' ? old.promise : current.promise);
  app.render(true); await flush();
  app.navigate('new'); app.render(true); await flush();
  assert.equal(app.calls[0].signal.aborted, true);
  current.resolve(research(prop('new'))); await flush();
  old.resolve(research(prop('old'))); await flush(); app.render();
  assert.equal(nodes(app.tree(), 'select').find(node => node.props['aria-label'] === 'Research market').props.value, 'new');
  app.cleanup();
});

test('unknown UUID and ambiguous research links show error without default fallback', async () => {
  for (const status of [404, 409, 422]) {
    const app = harness('unknown', async () => { throw { status }; });
    app.render(true); await flush(); app.render();
    assert.equal(app.calls.length, 1);
    assert.deepEqual(app.calls[0].params, { prop_id: 'unknown' });
    assert.equal(app.navigation.length, 0);
    assert.match(JSON.stringify(app.tree()), /unavailable|ambiguous|malformed/);
    app.cleanup();
  }
});

test('cleanup aborts pending research and cannot publish results after unmount', async () => {
  const request = deferred();
  const app = harness('pinned', () => request.promise);
  app.render(true); await flush(); app.cleanup();
  assert.equal(app.calls[0].signal.aborted, true);
  request.resolve(research(prop('pinned'))); await flush();
  assert.equal(app.navigation.length, 0);
});

test('primary unavailability keeps history and explicitly eligible alternative book visible', async () => {
  const selected = prop('pinned', 'event-a', { actionable: false, availability: 'expired', over_odds: null, under_odds: null,
    best_over: { sportsbook: 'DraftKings', line: 20.5, odds: 115 },
    sportsbook_offers: [{ sportsbook: 'DraftKings', line: 20.5, over_odds: 115, under_odds: -110,
      actionable: true, provider_observed_at: new Date().toISOString(), expires_at: '2099-10-20T18:00:00Z' }] });
  const app = harness('pinned', async () => research(selected));
  app.render(true); await flush(); app.render();
  const text = JSON.stringify(app.tree());
  assert.match(text, /DraftKings 115|DraftKings \+115/);
  assert.match(text, /FanDuel/);
  assert.match(text, /no_history/); // component remains independent of trends and current offer status
  app.cleanup();
});

test('stale request failures cannot replace a newer UUID result', async () => {
  const old = deferred();
  const app = harness('old', params => params.prop_id === 'old' ? old.promise : Promise.resolve(research(prop('new'))));
  app.render(true); await flush();
  app.navigate('new'); app.render(true); await flush();
  old.reject({ status: 404 }); await flush(); app.render();
  assert.equal(nodes(app.tree(), 'select').find(node => node.props['aria-label'] === 'Research market').props.value, 'new');
  assert.equal(nodes(app.tree(), 'p').filter(node => node.props.role === 'alert').length, 0);
  app.cleanup();
});

test('offset-aware and naive UTC snapshot timestamps render the same Eastern time', async () => {
  const result = research(prop('pinned'));
  result.line_movement = { sportsbook: 'FanDuel', snapshot_count: 2, opening_line: 20.5, current_line: 21.5,
    line_change: 1, opened_at: '2026-10-14T15:00:00+00:00', updated_at: '2026-10-14T15:00:00',
    opening_over_odds: -110, opening_under_odds: -110, current_over_odds: -110, current_under_odds: -110 };
  const app = harness('pinned', async () => result);
  app.render(true); await flush(); app.render();
  const timestamps = nodes(app.tree(), 'p').filter(node => typeof node.props.children === 'string' && node.props.children.includes('11:00 AM'));
  assert.equal(timestamps.length, 2);
  assert.equal(timestamps[0].props.children, timestamps[1].props.children);
  app.cleanup();
});

test('legacy context is explicitly unverified and same-line market options keep distinct UUIDs', async () => {
  const selected = prop('one', null, { identity_source: 'legacy', game_key: 'NBA|2099-10-20T19:00:00|Away|Home' });
  const another = { ...selected, id: 'two' };
  const app = harness('one', async () => research(selected, [selected, another]));
  app.render(true); await flush(); app.render();
  const game = nodes(app.tree(), 'select').find(node => node.props['aria-label'] === 'Research game');
  const market = nodes(app.tree(), 'select').find(node => node.props['aria-label'] === 'Research market');
  assert.match(JSON.stringify(game), /Legacy \/ unverified/);
  assert.deepEqual(nodes(market, 'option').map(node => node.props.value), ['one', 'two']);
  market.props.onChange({ target: { value: 'two' } });
  assert.deepEqual(app.navigation.at(-1), ['push', '/player/player?prop_id=two']);
  app.cleanup();
});

test('player route change hides previous header and history until the new player succeeds', async () => {
  const nextPlayer = deferred();
  const app = harness('first-prop', async params => research(prop(params.prop_id)), id => id === 'player'
    ? Promise.resolve({ id, name: 'First Player', sport: 'NBA', props: [] }) : nextPlayer.promise);
  app.render(true); await flush(); app.render();
  assert.match(JSON.stringify(app.tree()), /First Player/);
  app.navigatePlayer('second-player', 'second-prop'); app.render(true);
  assert.doesNotMatch(JSON.stringify(app.tree()), /First Player|first-prop|no_history/);
  nextPlayer.resolve({ id: 'second-player', name: 'Second Player', sport: 'NBA', props: [] });
  await flush(); app.render();
  assert.match(JSON.stringify(app.tree()), /Second Player/);
  assert.doesNotMatch(JSON.stringify(app.tree()), /First Player|first-prop/);
  assert.equal(nodes(app.tree(), 'select').find(node => node.props['aria-label'] === 'Research market').props.value, 'second-prop');
  app.cleanup();
});

test('failed player route change cannot expose the previous player research snapshot', async () => {
  const nextPlayer = deferred();
  const app = harness('first-prop', async params => research(prop(params.prop_id)), id => id === 'player'
    ? Promise.resolve({ id, name: 'First Player', sport: 'NBA', props: [] }) : nextPlayer.promise);
  app.render(true); await flush(); app.render();
  app.navigatePlayer('missing-player', 'other-prop'); app.render(true);
  assert.doesNotMatch(JSON.stringify(app.tree()), /First Player|first-prop|no_history/);
  nextPlayer.reject({ status: 404 }); await flush(); app.render();
  assert.doesNotMatch(JSON.stringify(app.tree()), /First Player|first-prop|no_history/);
  assert.match(JSON.stringify(app.tree()), /Player research unavailable/);
  assert.equal(nodes(app.tree(), 'select').filter(node => node.props['aria-label'] !== 'NBA statistics season').length, 0);
  assert.equal(app.calls.length, 1);
  app.cleanup();
});

test('player-only research retains additive season summary without inventing a selected prop', async () => {
  const season = { status: 'available', season: '2025-26', recorded_appearances: 6 };
  const app = harness(null, async () => ({ ...research(null, []), season_summary: season }));
  app.render(true); await flush(); app.render();
  assert.match(JSON.stringify(app.tree()), /2025-26/);
  assert.equal(app.calls[0].params, undefined);
  assert.equal(nodes(app.tree(), 'select').filter(node => node.props['aria-label'] !== 'NBA statistics season').length, 0);
  assert.equal(app.navigation.length, 0);
  app.cleanup();
});

test('same-player Prop navigation hides the old season summary until the new selection resolves', async () => {
  const next = deferred();
  const first = { ...research(prop('first')), season_summary: { reference_date: '2099-10-20', notes: ['first summary marker'] } };
  const second = { ...research(prop('second', 'event-b')), season_summary: { reference_date: '2099-10-22', notes: ['second summary marker'] } };
  const app = harness('first', params => params.prop_id === 'first' ? Promise.resolve(first) : next.promise);
  app.render(true); await flush(); app.render();
  assert.match(JSON.stringify(app.tree()), /first summary marker/);
  app.navigate('second'); app.render(true);
  assert.doesNotMatch(JSON.stringify(app.tree()), /first summary marker|2099-10-20"/);
  await flush(); app.render();
  assert.doesNotMatch(JSON.stringify(app.tree()), /first summary marker/);
  next.resolve(second); await flush(); app.render();
  assert.match(JSON.stringify(app.tree()), /second summary marker/);
  assert.doesNotMatch(JSON.stringify(app.tree()), /first summary marker/);
  app.cleanup();
});

test('failed same-player Prop navigation keeps the previous reference-date summary hidden', async () => {
  const next = deferred();
  const first = { ...research(prop('first')), season_summary: { reference_date: '2099-10-20', notes: ['first summary marker'] } };
  const app = harness('first', params => params.prop_id === 'first' ? Promise.resolve(first) : next.promise);
  app.render(true); await flush(); app.render();
  assert.match(JSON.stringify(app.tree()), /first summary marker/);
  app.navigate('missing'); app.render(true); await flush(); app.render();
  assert.doesNotMatch(JSON.stringify(app.tree()), /first summary marker/);
  next.reject({ status: 404 }); await flush(); app.render();
  assert.equal(nodes(app.tree(), 'p').filter(node => node.props.role === 'alert').length, 1);
  assert.doesNotMatch(JSON.stringify(app.tree()), /first summary marker/);
  assert.equal(nodes(app.tree(), 'select').find(node => node.props['aria-label'] === 'Research market').props.value, '');
  app.cleanup();
});
