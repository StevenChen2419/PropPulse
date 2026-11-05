const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const filename = path.resolve(__dirname, '../src/components/MatchupContextSection.tsx');
const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
} }).outputText;
const mod = new Module(filename, module);
mod.filename = filename; mod.paths = Module._nodeModulePaths(path.dirname(filename)); mod._compile(compiled, filename);
const render = data => renderToStaticMarkup(React.createElement(mod.exports.MatchupContextSection, { data }));

const window = (appearances = 2) => ({ appearances, coverage_start: '2026-10-04', coverage_end: '2026-10-17',
  points: { average: 0, valid_samples: 2 }, rebounds: { average: 3.5, valid_samples: 1 },
  assists: { average: null, valid_samples: 0 }, minutes: { average: 30, valid_samples: 2 } });
const fixture = () => ({ status: 'available', reason: null,
  team_context: { team_id: '1610612738', team_name: 'Boston Celtics', opponent_id: '1610612753',
    opponent_name: 'Orlando Magic', reference_date: '2026-10-18', event_id: 'event', prop_id: 'prop',
    last_recorded_game: { game_id: '0022600001', date: '2026-10-17', source: 'nba_api.stats.leaguegamelog', observed_at: '2026-10-18T12:00:00Z', date_precision: 'eastern_date' },
    calendar_day_gap: 1, full_intervening_days: 0, conditional_back_to_back: 'yes', notes: ['Recorded schedule coverage is partial.'] },
  opponent_history: { status: 'available', opponent_id: '1610612753', opponent_name: 'Orlando Magic', season: '2026-27', competition: 'Regular Season', source: 'nba_com_stats', recorded_appearances: 2,
    coverage_start: '2026-10-04', coverage_end: '2026-10-17', overall: window(), l5: window(), l10: window(), notes: [] } });

test('team result dates, conditional back-to-back and independent opponent denominators', () => {
  const html = render(fixture());
  for (const text of [/Matchup &amp; Team Rest/, /Orlando Magic/, /Oct 17, 2026/, /Oct 18, 2026/, /Full intervening team rest days/, />0</,
    /Yes, if the team plays the selected game/, /2 recorded appearances/, /2 games/, />0\.0</, /1\/2 valid/, /0\/2 valid/, /Unavailable/,
    /Partial recorded coverage/, /2026-27/, /NBA.com/, /descriptive context/, /not individual player rest/, /Opponent appearance window dates/]) assert.match(html, text);
});
test('missing identity uses one concise state without metric panels', () => {
  const html = render({ status: 'unavailable', reason: 'Recent supported player team context unavailable.', team_context: null, opponent_history: null });
  assert.match(html, /Recent supported player team context unavailable/);
  assert.doesNotMatch(html, /<table|Back-to-back|Unknown|0\.0/);
  assert.equal(render(null), '');
});
test('missing team results and unknown negative back-to-back stay unavailable', () => {
  const data = fixture(); Object.assign(data.team_context, { last_recorded_game: null, calendar_day_gap: null, full_intervening_days: null, conditional_back_to_back: 'unknown' });
  data.opponent_history.status = 'unavailable';
  const html = render(data);
  assert.match(html, /Unknown .*incomplete schedule coverage/);
  assert.match(html, /No supported opponent appearances/);
  assert.doesNotMatch(html, /<table|>0<|>No</);
});
