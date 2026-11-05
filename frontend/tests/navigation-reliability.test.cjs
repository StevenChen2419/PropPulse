const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');

function load(file, mocks = {}) {
  const filename = path.resolve(__dirname, '../src', file);
  const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  }).outputText;
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const native = mod.require.bind(mod);
  mod.require = name => {
    if (name in mocks) return mocks[name];
    if (name.startsWith('@/') || name.startsWith('./')) {
      const target = name.startsWith('@/') ? path.resolve(__dirname, '../src', name.slice(2)) : path.resolve(path.dirname(filename), name);
      return load(target + (fs.existsSync(target + '.ts') ? '.ts' : '.tsx'), mocks);
    }
    return native(name);
  };
  mod._compile(compiled, filename);
  return mod.exports;
}

const nav = load('lib/gameNavigation.ts');
const id = '6ff2324d-5dcb-455b-be37-2ad4dab5370a';
const key = 'NBA|2026-10-20T19:00:00|Away|Home';

test('canonical route and filter identity survive schedule and legacy field changes', () => {
  const game = { event_id: id, game_key: key, identity_source: 'authoritative' };
  assert.equal(nav.gameHref(game), `/games/${id}`);
  assert.equal(nav.gameHref({ ...game, game_key: 'changed', scheduled_start_at: '2099-10-22T20:00:00Z' }), `/games/${id}`);
  assert.deepEqual(nav.gameQuery(nav.gameIdentityValue(game)), { event_id: id });
  assert.deepEqual(nav.gameQuery(id), { event_id: id });
  assert.deepEqual(nav.gameQuery('malformed-uuid'), { event_id: 'malformed-uuid' });
});

test('legacy compatibility routes preserve opaque keys without manufacturing UUIDs', () => {
  assert.equal(nav.gameHref({ event_id: null, game_key: key }), '/games/' + encodeURIComponent(key));
  assert.deepEqual(nav.gameQuery(nav.gameIdentityValue({ game_key: key })), { game_key: key });
  assert.deepEqual(nav.gameQuery(key), { game_key: key });
  assert.equal(nav.gameIdentityValue({ identity_source: 'unresolved' }), '');
  const literalEscape = key.replace('Away', 'Away%20Team');
  assert.equal(nav.decodeGameSegment(encodeURIComponent(literalEscape)), literalEscape);
  assert.equal(nav.decodeGameSegment(literalEscape), literalEscape);
});

test('prop research links preserve exact UUID without market or betting-line selectors', () => {
  const href = nav.propResearchHref('player-one', 'prop-one');
  const url = new URL(href, 'http://example.invalid');
  assert.equal(url.pathname, '/player/player-one');
  assert.deepEqual([...url.searchParams], [['prop_id', 'prop-one']]);
});

test('latest request wins even when an old transport ignores cancellation', async () => {
  const gate = load('lib/requestGate.ts').createRequestGate();
  const old = gate.start();
  let finishOld;
  let state;
  const pending = new Promise(resolve => { finishOld = resolve; }).then(value => { if (old.isCurrent()) state = value; });
  const current = gate.start();
  assert.equal(old.signal.aborted, true);
  if (current.isCurrent()) state = 'new-prop';
  finishOld('previous-event');
  await pending;
  assert.equal(state, 'new-prop');
  gate.cancel();
  assert.equal(current.signal.aborted, true);
  assert.equal(current.isCurrent(), false);
  assert.equal(gate.start().isCurrent(), true, 'Strict Mode remount can issue a fresh request');
});

test('API forwards abort signals and status codes while page errors hide internal details', async () => {
  const original = global.fetch;
  const { api, ApiError } = load('lib/api.ts');
  const controller = new AbortController();
  let received;
  global.fetch = async (_url, options) => { received = options.signal; return { ok: true, json: async () => ({}) }; };
  try {
    await api.getPlayerResearch('player', { prop_id: 'prop' }, controller.signal);
    assert.equal(received, controller.signal);
    for (const status of [400, 404, 409, 422, 500]) {
      global.fetch = async () => ({ ok: false, status, json: async () => ({ detail: 'INTERNAL database traceback' }) });
      await assert.rejects(api.getGame({ event_id: id }), error => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, status);
        assert.doesNotMatch(nav.errorMessage(error, 'game'), /INTERNAL|database|traceback/);
        return true;
      });
    }
    assert.match(nav.errorMessage(new TypeError('fetch failed'), 'research'), /connection/);
  } finally { global.fetch = original; }
});

test('PropCard links to exact research and uses authoritative participants', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { PropCard } = load('components/PropCard.tsx', {
    'next/navigation': { useRouter: () => ({ push() {} }) },
    'next/link': { __esModule: true, default: ({ children, ...props }) => React.createElement('a', props, children) },
    '@/lib/useOfferClock': { useOfferClock() {} },
  });
  const prop = { id: 'prop-one', player: { id: 'player-one', name: 'Fixture Player', team_abbr: 'TRADED' },
    event_id: id, home_team: 'Verified Home', away_team: 'Verified Away', scheduled_start_at: '2099-10-20T19:00:00Z',
    game_time: '2099-10-20T19:00:00Z', opponent: 'STALE OPPONENT', is_home: true, prop_type: 'points', line: 20.5,
    sportsbook: 'FanDuel', sportsbook_offers: [], over_odds: null, under_odds: null, actionable: false };
  const html = renderToStaticMarkup(React.createElement(PropCard, { prop }));
  assert.match(html, /href="\/player\/player-one\?prop_id=prop-one&amp;sportsbook=FanDuel&amp;offer_line=20.5&amp;side=under"/);
  assert.match(html, /Verified Away @ Verified Home/);
  assert.doesNotMatch(html, /STALE OPPONENT/);
});
