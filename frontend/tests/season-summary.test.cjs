const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const filename = path.resolve(__dirname, '../src/components/PlayerSeasonSummary.tsx');
const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
} }).outputText;
const mod = new Module(filename, module);
mod.filename = filename; mod.paths = Module._nodeModulePaths(path.dirname(filename));
const nativeRequire = mod.require.bind(mod);
mod.require = name => name.startsWith('@/') ? require('./load-source.cjs').loadSource(name.slice(2)) : nativeRequire(name);
mod._compile(compiled, filename);
const render = (data, now = '2026-01-12T12:00:00Z') => renderToStaticMarkup(React.createElement(mod.exports.PlayerSeasonSummary, { data, now: new Date(now) }));
const summary = () => ({
  status: 'available', season: '2025-26', competition: 'Regular Season', source: 'nba_com_stats',
  coverage_start: '2026-01-02', coverage_end: '2026-01-09', last_observed_at: '2026-01-10T00:30:00Z',
  recorded_appearances: 6, latest_appearance: '2026-01-09', date_precision: 'eastern_date',
  reference_date: '2026-01-12', calendar_day_gap: 3, full_intervening_days: 2,
  l5: { appearances: 5, points: { average: 0, valid_samples: 4 }, rebounds: { average: 6.5, valid_samples: 4 },
    assists: { average: null, valid_samples: 0 }, minutes: { average: 31.25, valid_samples: 3 } },
  l10: { appearances: 6, points: { average: 12.5, valid_samples: 5 }, rebounds: { average: 7, valid_samples: 5 },
    assists: { average: 3, valid_samples: 1 }, minutes: { average: 29.5, valid_samples: 4 } },
  notes: ['Offline fixture coverage; not live NBA coverage.'],
});

test('season summary shows independent samples, valid zero and missing values in fixed windows', () => {
  const html = render(summary());
  for (const text of [/Recent Performance/, /Points/, /Rebounds/, /Assists/, /Minutes/, /5 appearances/, /6 appearances/,
    /4\/5 valid/, /0\/5 valid/, /3\/5 valid/, /5\/6 valid/, />0\.0</, /Unavailable/, /31\.3/,
    /missing values do not add older games/]) assert.match(html, text);
});

test('calendar-only appearance dates remain exact and observation times use Eastern', () => {
  const html = render(summary());
  for (const text of [/Jan 9, 2026/, /Jan 12, 2026 \(Eastern\)/, /7:30 PM EST/,
    /Calendar days since/, /Full intervening days/, />3</, />2</, /game times are unavailable/,
    /do not establish missed games/]) assert.match(html, text);
  assert.doesNotMatch(html, /Jan 8, 2026|12:30 AM/);
});

test('coverage makes provider, partial season and fixture provenance visible', () => {
  const html = render(summary());
  for (const text of [/2025-26/, /Regular Season/, /NBA.com · NBA Stats/, /6 recorded appearances/, /Jan 2, 2026/,
    /complete season history/, /Offline fixture coverage; not live NBA coverage/]) assert.match(html, text);
});

test('unavailable scopes use one concise state and absent additive responses render nothing', () => {
  assert.equal(render(undefined), ''); assert.equal(render(null), '');
  const html = render({ ...summary(), status: 'unavailable', notes: ['No accepted statistics in scope.'] });
  assert.match(html, /Season statistics unavailable/);
  assert.match(html, /No accepted statistics in scope/);
  assert.doesNotMatch(html, /<table|Calendar days since|Unknown|0\.0/);
});

test('legacy naive observation timestamps are interpreted as UTC without changing appearance dates', () => {
  const data = summary(); data.last_observed_at = '2026-01-10T00:30:00';
  assert.equal(render(data), render(summary()));
});

test('ESPN fallback remains visibly separate from NBA.com statistics', () => {
  const data = summary(); data.source = 'espn_nba';
  assert.match(render(data), /ESPN/); assert.doesNotMatch(render(data), /NBA.com · NBA Stats/);
});

test('completed older seasons are labeled historical against the Eastern reference season', () => {
  for (const status of ['available', 'unavailable']) {
    const html = render({ ...summary(), status }, '2026-10-19T12:00:00Z');
    assert.match(html, /Historical Performance/);
    assert.match(html, /Historical season statistics; not current live form\./);
    assert.doesNotMatch(html, /Recent Performance/);
  }
});

test('same season keeps recent heading across January and September until October rollover', () => {
  for (const reference_date of ['2025-10-01', '2026-01-12', '2026-09-30']) {
    const html = render(summary(), `${reference_date}T12:00:00Z`);
    assert.match(html, /Recent Performance/);
    assert.doesNotMatch(html, /Historical season statistics|Historical Performance/);
  }
});


test('old selected Event does not relabel historical season as current form', () => {
  assert.match(render(summary(), '2026-10-19T12:00:00Z'), /Historical Performance/);
});

test('empty current season identifies missing NBA.com appearances separately from odds and team context', () => {
  const html = render({ ...summary(), status: 'unavailable', season: '2026-27', source: null, notes: [] }, '2026-10-19T12:00:00Z');
  assert.match(html, /No NBA.com appearances recorded for this season and competition/);
  assert.match(html, /Source unavailable/);
  assert.match(html, /separate from sportsbook odds and team context/);
  assert.match(html, /L5\/L10 and player rest are unavailable/);
  assert.doesNotMatch(html, /<table|NBA.com � NBA Stats|Historical Performance/);
});

test('two current appearances show actual partial L5 and L10 samples', () => {
  const data = summary(); data.season = '2026-27';
  for (const key of ['l5', 'l10']) data[key] = { ...data[key], appearances: 2, points: { average: 14, valid_samples: 2 } };
  const html = render(data, '2026-10-24T12:00:00Z');
  assert.equal((html.match(/2 appearances/g) || []).length, 2);
  assert.equal((html.match(/2\/2 valid/g) || []).length, 2);
  assert.match(html, /Recent Performance/);
});

test('NBA three-pointers use the additive metric contract with partial and missing samples', () => {
  const data = summary(); data.season = '2026-27';
  data.metrics = [{ key: 'points', label: 'Points' }, { key: 'threes', label: '3PM' }];
  data.l5 = { ...data.l5, appearances: 2, threes: { average: 0, valid_samples: 1 } };
  data.l10 = { ...data.l10, appearances: 2, threes: { average: null, valid_samples: 0 } };
  const html = render(data, '2026-10-24T12:00:00Z');
  assert.match(html, /3PM/); assert.match(html, /1\/2 valid/); assert.match(html, /0\/2 valid/);
  assert.match(html, />0\.0</); assert.match(html, /Unavailable/);
});
