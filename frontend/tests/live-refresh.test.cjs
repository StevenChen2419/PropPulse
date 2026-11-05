const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
function load(file, mocks = {}) {
  const filename = path.resolve(__dirname, '../src/lib', file);
  const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const nativeRequire = mod.require.bind(mod);
  mod.require = name => mocks[name] || nativeRequire(name);
  mod._compile(compiled, filename);
  return mod.exports;
}
test('live requests bypass browser caches', async () => {
  const original = global.fetch;
  let request;
  global.fetch = async (url, options) => { request = { url, options }; return { ok: true, json: async () => [] }; };
  try {
    await load('api.ts').api.getGames({ sport: 'NFL' });
    assert.match(request.url, /sport=NFL/);
    assert.equal(request.options.cache, 'no-store');
  } finally { global.fetch = original; }
});
test('refresh skips hidden/offline/busy pages and overlapping requests, and cleans up', async () => {
  const descriptors = Object.fromEntries(['window', 'document', 'navigator'].map(key => [key, Object.getOwnPropertyDescriptor(global, key)]));
  const events = new Map();
  let tick, cleanup, interval, cleared, calls = 0, finish;
  const ref = { current: null };
  const browser = { addEventListener: (name, fn) => events.set(name, fn), removeEventListener: name => events.delete(name) };
  Object.defineProperty(global, 'window', { configurable: true, value: { ...browser, setInterval: (fn, ms) => { tick = fn; interval = ms; return 42; }, clearInterval: id => { cleared = id; } } });
  Object.defineProperty(global, 'document', { configurable: true, value: { ...browser, visibilityState: 'visible' } });
  Object.defineProperty(global, 'navigator', { configurable: true, value: { onLine: true } });
  try {
    const { useLiveRefresh } = load('useLiveRefresh.ts', { react: { useRef: () => ref, useEffect: fn => { cleanup = fn(); } } });
    useLiveRefresh(() => { calls++; return new Promise(resolve => { finish = resolve; }); });
    assert.equal(interval, 60000);
    const first = tick(); await tick(); assert.equal(calls, 1);
    finish(); await first;
    document.visibilityState = 'hidden'; await tick(); assert.equal(calls, 1);
    document.visibilityState = 'visible'; navigator.onLine = false; await tick(); assert.equal(calls, 1);
    navigator.onLine = true; ref.current.busy = true; await tick(); assert.equal(calls, 1);
    ref.current.busy = false;
    const resumed = events.get('visibilitychange')(); assert.equal(calls, 2); finish(); await resumed;
    const online = events.get('online')(); assert.equal(calls, 3); finish(); await online;
    cleanup(); assert.equal(cleared, 42); assert.equal(events.size, 0);
    await tick(); assert.equal(calls, 3);
  } finally {
    for (const [key, descriptor] of Object.entries(descriptors)) {
      if (descriptor) Object.defineProperty(global, key, descriptor); else delete global[key];
    }
  }
});

test('game history never invents historical betting hits or zero-point games', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { PlayerStatsChart } = load('../components/PlayerStatsChart.tsx');
  const missing = renderToStaticMarkup(React.createElement(PlayerStatsChart, { games: [{ game_date: '2026-09-10', actual_points: null }] }));
  assert.match(missing, /No observed points history available/);
  const observed = renderToStaticMarkup(React.createElement(PlayerStatsChart, { games: [
    { game_date: '2026-09-10', actual_points: 0 },
    { game_date: '2026-09-09', actual_points: null },
  ] }));
  assert.match(observed, /Last 1 games with points data/);
  assert.doesNotMatch(observed, /Hit line|Mock data|Gundefined/);
});

test('offer clock reevaluates local expiry offline and cleans up its timer', () => {
  const originalSet = global.setInterval;
  const originalClear = global.clearInterval;
  let tick, cleanup, value = 0, cleared;
  global.setInterval = (fn, delay) => { assert.equal(delay, 1000); tick = fn; return 77; };
  global.clearInterval = (id) => { cleared = id; };
  try {
    const { useOfferClock } = load('useOfferClock.ts', { react: {
      useState: () => [value, (update) => { value = update(value); }],
      useEffect: (effect) => { cleanup = effect(); },
    } });
    useOfferClock(); tick(); assert.equal(value, 1);
    cleanup(); assert.equal(cleared, 77);
  } finally { global.setInterval = originalSet; global.clearInterval = originalClear; }
});
