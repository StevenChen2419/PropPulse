const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { restWorkload } = require('./fixtures/rest-workload.cjs');
const filename = path.resolve(__dirname, '../src/components/RestWorkloadSection.tsx');
const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: {
  module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
} }).outputText;
const mod = new Module(filename, module);
mod.filename = filename; mod.paths = Module._nodeModulePaths(path.dirname(filename)); mod._compile(compiled, filename);
const { RestWorkloadSection } = mod.exports;
const render = data => renderToStaticMarkup(React.createElement(RestWorkloadSection, { data }));

test('research separates observations, derived gaps and heuristic interpretation with coverage', () => {
  const html = render(restWorkload());
  for (const pattern of [/Observed minutes/, /Recorded appearances: derived rest context/, /Heuristic interpretation/, /No predictive model/, /Schedule coverage is incomplete/, /10 eligible of 13 stored/, /Duplicate game: 1/, /Future game: 1/, /Unverified source: 1/, /No predictive model/, /Possession-based usage is unavailable/]) {
    assert.match(html, pattern);
  }
  assert.match(html, /0.43 games\/day/);
  assert.match(html, /Data coverage &amp; calculation details/);
  assert.match(html, /L5 vs season average/);
  assert.match(html, /\+1.0 min/);
  assert.match(html, /Limited sample/);
  assert.match(html, /Seasons: 2026, 2027/);
  assert.match(html, /Points: 22.0 \(2 games\)/);
  assert.doesNotMatch(html, /win probability|High Risk|guaranteed decline/);
});

test('unknown minutes and rest remain explicit, never zero or negative claims', () => {
  const data = restWorkload(); data.status = 'no_history';
  Object.assign(data.rest, { days_since_last_game: null, back_to_back: null, category: null, games_in_7d: null, games_in_14d: null, schedule_density: null });
  for (const key of ['l5', 'l10', 'season']) Object.assign(data.workload[key], { games: 0, observed_games: 0, average_minutes: null, seasons: [], date_start: null, date_end: null, insufficient_sample: true });
  Object.assign(data.workload, { l5_vs_season: null, minutes_trend: null, variability: null });
  const html = render(data);
  assert.match(html, /No eligible completed game observations/);
  assert.match(html, /Unknown/); assert.match(html, /Unavailable/); assert.match(html, /No dated sample/);
  assert.doesNotMatch(html, />No<|0\.0 min|0\.00 games\/day/);
});

test('UTC game instants render on the Eastern calendar and preserve sample dates', () => {
  const data = restWorkload(); data.reference.at = '2026-10-12T00:30:00Z';
  data.workload.l5.date_start = '2026-10-02T00:30:00Z';
  const html = render(data);
  assert.match(html, /Oct 11, 2026 \(Eastern\)/);
  assert.match(html, /Oct 1, 2026/);
});

test('older API responses omit the additive section and other sports explain support', () => {
  assert.equal(render(undefined), '');
  const data = restWorkload(); data.status = 'unsupported_sport'; data.sport = 'MLB';
  const html = render(data); assert.match(html, /NBA players only/); assert.doesNotMatch(html, /34\.0 min/);
});

test('confirmed player rest remains separate from team back-to-back with exact missed games', () => {
  const { verifiedRest } = require('./fixtures/rest-workload.cjs');
  const html = render({ ...restWorkload(), verified: verifiedRest() });
  assert.match(html, /Player rest/); assert.match(html, /Team schedule/);
  assert.match(html, /Team context comes from dated membership/);
  assert.match(html, /provider game identities do not establish an association with the selected Event/);
  assert.match(html, /3 \/ 2 days/); assert.match(html, /1 \/ 0 days/);
  assert.match(html, /Yes · Confirmed/); assert.match(html, /1 · Confirmed/);
  assert.match(html, /1 DNP · 0 inactive/);
  assert.match(html, /Unknown participation: 0 games/);
  assert.match(html, /Recorded appearances: derived rest context/);
  assert.match(html, /Oct 8, 2026 · Confirmed/); assert.match(html, /Oct 10, 2026 · Confirmed/);
});

test('partial evidence exposes a lower bound and unknown team b2b without false zero missed games', () => {
  const { verifiedRest } = require('./fixtures/rest-workload.cjs');
  const html = render({ ...restWorkload(), verified: verifiedRest({ status: 'partial', confirmed_missed_games: null,
    partial_missed_games_lower_bound: 1, unknown_participation_games: 2, uncovered_games: 3,
    team_back_to_back: null, schedule_complete: false }) });
  assert.match(html, /At least 1 · Partial coverage/);
  assert.match(html, /Unknown participation: 2 games/); assert.match(html, /Uncovered schedule: 3 games/);
  assert.match(html, /Back-to-back if playing on reference date<\/dt><dd[^>]*>Unknown/);
  assert.doesNotMatch(html, /0 · Confirmed|No · Confirmed/);
});

test('missing verified evidence is explicitly unknown despite existing observed appearance metrics', () => {
  const html = render(restWorkload());
  assert.match(html, /Participation and final-game evidence: .*Unknown/);
  assert.match(html, /Player date gap \/ full intervening rest days<\/dt><dd[^>]*>Unknown/);
  assert.match(html, /Confirmed missed team games<\/dt><dd[^>]*>Unknown/);
  assert.match(html, /Missing logs do not establish DNP/);
  assert.doesNotMatch(html, /0 · Confirmed/);
});

test('explicit unknown evidence counts stay unknown and a confirmed zero requires evidence', () => {
  const { verifiedRest } = require('./fixtures/rest-workload.cjs');
  const unknown = verifiedRest({ status: 'unknown', confirmed_missed_games: null, partial_missed_games_lower_bound: 0,
    last_confirmed_appearance: null, last_completed_team_game: null, team_back_to_back: null, schedule_complete: false });
  assert.match(render({ ...restWorkload(), verified: unknown }), /Unknown participation: Unknown · Uncovered schedule: Unknown/);
  assert.match(render({ ...restWorkload(), verified: verifiedRest({ confirmed_missed_games: 0, partial_missed_games_lower_bound: 0 }) }), /0 · Confirmed/);
});


test('team-only partial evidence cannot turn missing player baseline into zero unknown games', () => {
  const { verifiedRest } = require('./fixtures/rest-workload.cjs');
  const verified = verifiedRest({ status: 'partial', last_confirmed_appearance: null,
    confirmed_missed_games: null, partial_missed_games_lower_bound: null,
    unknown_participation_games: 0, uncovered_games: 0,
    last_completed_team_game: { ...verifiedRest().last_completed_team_game, status: 'partial' } });
  const html = render({ ...restWorkload(), verified });
  assert.match(html, /Unknown participation: Unknown · Uncovered schedule: Unknown/);
  assert.match(html, /Oct 10, 2026 · Partial coverage/);
  assert.match(html, /Confirmed missed team games<\/dt><dd[^>]*>Unknown/);
  assert.doesNotMatch(html, /Unknown participation: 0|Uncovered schedule: 0/);
});

test('NBA.com evidence preserves provenance and partial metrics alongside existing ESPN observations', () => {
  const { nbaVerifiedRest } = require('./fixtures/rest-workload.cjs');
  const html = render({ ...restWorkload(), verified: nbaVerifiedRest() });
  assert.match(html, /Participation and final-game evidence: .*Partial coverage/);
  assert.match(html, /Oct 8, 2026 · Partial coverage/);
  assert.match(html, /3 \/ 2 days/);
  assert.match(html, /Previous final team game in coverage<\/dt><dd[^>]*>Unknown/);
  assert.match(html, /Team date gap \/ full intervening rest days<\/dt><dd[^>]*>Unknown/);
  assert.match(html, /Back-to-back if playing on reference date<\/dt><dd[^>]*>Unknown/);
  assert.match(html, /Confirmed missed team games<\/dt><dd[^>]*>Unknown/);
  assert.match(html, /Sources: NBA.com PlayerGameLog, NBA.com LeagueGameLog/);
  assert.equal((html.match(/Eastern calendar date only; actual game time unavailable\./g) || []).length, 1);
  assert.match(html, /Sources: espn_nba/);
  assert.doesNotMatch(html, /0 · Confirmed|Yes · Confirmed|ESPN game/);
});
