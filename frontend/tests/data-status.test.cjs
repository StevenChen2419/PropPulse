const test = require('node:test');
const assert = require('node:assert/strict');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { loadSource } = require('./load-source.cjs');
const { OddsStatus, StatisticsStatus } = loadSource('components/DataStatus.tsx');
const { isActionable, availabilityLabel, getSelectionOdds } = loadSource('lib/propSides.ts');
const now = Date.parse('2026-10-20T18:00:00Z');
const gameTime = new Date(now + 86400000).toISOString();
const offer = (age) => ({ actionable: true, provider_observed_at: new Date(now-age).toISOString(),
  refreshed_at: new Date(now).toISOString(), ingested_at: new Date(now).toISOString(),
  expires_at: new Date(now + 86400000).toISOString(), odds: -110 });
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));
const coverage = () => ({ state: 'partial_current_season', completeness: 'unknown', season_scope: 'current',
  season: '2026', competition: 'Regular Season', source: 'wehoop_wnba_stats', last_game_date: '2026-07-22',
  source_observed_at: '2026-10-20T12:00:00Z', recorded_appearances: 8, l5_samples: 5, l10_samples: 8,
  limitations: ['Source completeness is unknown.'] });

test('provider observations override re-ingestion and drive price transitions', t => {
  t.mock.method(Date, 'now', () => now);
  for (const [age, label, usable] of [[1800000, 'Live odds', true], [1800001, 'Last known odds', false],
    [21600000, 'Last known odds', false], [21600001, 'Expired odds', false]]) {
    const data = offer(age);
    assert.equal(availabilityLabel(data, gameTime), label);
    assert.equal(isActionable(data, gameTime), usable);
    const html = render(OddsStatus, { offer: data, gameTime });
    assert.match(html, new RegExp(label));
    assert.match(html, /Ingestion and page reload do not renew/);
  }
  assert.match(render(OddsStatus, { offer: offer(7200000), gameTime }), /observed 2h ago/);
  assert.equal(availabilityLabel(offer(0), new Date(now).toISOString()), 'Game started');
});

test('unknown observation disables persisted prices and never uses ingestion time', t => {
  t.mock.method(Date, 'now', () => now);
  const data = { ...offer(0), provider_observed_at: null };
  assert.equal(isActionable(data, gameTime), false);
  assert.equal(getSelectionOdds({ selection: data, game_time: gameTime }), null);
  const html = render(OddsStatus, { offer: data, gameTime });
  assert.match(html, /Market unavailable/); assert.match(html, /observation time unknown/);
  const future = offer(-1000);
  assert.equal(isActionable(future, gameTime), false);
});

test('old represented game and new source observation stay visibly independent', () => {
  const html = render(StatisticsStatus, { coverage: coverage() });
  for (const text of [/Stats through Jul 22, 2026/, /8 games/, /Partial sample/, /L5: 5 appearances/,
    /L10: 8 appearances/, /Source coverage uncertain/, /wehoop/, /Oct 20, 2026/,
    /does not determine sportsbook price availability/]) assert.match(html, text);
  assert.doesNotMatch(html, /complete coverage|Live odds/);
  assert.match(html, /<details/); assert.match(html, /<summary/);
});

test('historical, empty and unknown coverage have plain distinct messages', () => {
  const historical = render(StatisticsStatus, { coverage: { ...coverage(), state: 'historical_season', season_scope: 'historical', season: '2025' } });
  assert.match(historical, /Historical stats/);
  const empty = render(StatisticsStatus, { coverage: { ...coverage(), state: 'no_recorded_games', season: '2026-27', recorded_appearances: 0, last_game_date: null, source_observed_at: null } });
  assert.match(empty, /2026-27 · No completed games recorded/); assert.match(empty, /Source observed: Unknown/);
  assert.match(render(StatisticsStatus, {}), /Statistics coverage unavailable/);
});
