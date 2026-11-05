const test = require('node:test');
const assert = require('node:assert/strict');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { loadSource } = require('./load-source.cjs');
const { SportsbookComparison } = loadSource('components/SportsbookComparison.tsx');
const { getSelectionOdds, sameOffer, retainedOffer } = loadSource('lib/propSides.ts');
const now = Date.parse('2026-10-21T18:00:00Z');
const gameTime = '2026-10-22T18:00:00Z';
function fixture() {
  const offer = (sportsbook, line, odds, age = 0) => ({ sportsbook, line, odds,
    availability: age > 30 ? 'last_known' : 'available', actionable: age <= 30,
    provider_bookmaker_key: sportsbook.toLowerCase(), provider_title: sportsbook,
    provider_observed_at: new Date(now-age*60000).toISOString(), expires_at: new Date(now+21600000-age*60000).toISOString() });
  const fd = offer('FanDuel',2.5,-110), dk = offer('DraftKings',2.5,120), old = offer('BetMGM',2.5,300,31), alt = offer('FanDuel',3.5,200);
  return { prop_id:'invented-prop',player_id:'invented-player',event_id:'invented-event',market:'shots_on_goal',groups:[
    {line:2.5,side:'over',offers:[fd,dk,old],best:dk,advantage_per_100:29.0909},
    {line:3.5,side:'over',offers:[alt],best:alt,advantage_per_100:null},
    {line:2.5,side:'under',offers:[],best:null,advantage_per_100:null},
  ] };
}
const render = (comparison, side = 'over') => renderToStaticMarkup(React.createElement(SportsbookComparison,
  {comparison,side,line:2.5,sportsbook:'DraftKings',gameTime,onSelect(){}}));

test('same-line best and alternative lines stay separate with exact research buttons', t => {
  t.mock.method(Date,'now',()=>now);
  const data = fixture(), before = structuredClone(data);
  const html = render(data);
  assert.match(html,/Best live price: DraftKings \+120/);
  assert.match(html,/Over 2.5|over 2.5/);
  assert.match(html,/Selected line/); assert.match(html,/Alternative line/);
  assert.match(html,/\$29.09 more profit per \$100 stake/);
  assert.match(html,/BetMGM · \+300/); assert.match(html,/Last known odds/);
  assert.doesNotMatch(html,/Best live price: BetMGM/);
  assert.match(html,/aria-pressed="true"/);
  assert.match(html,/Use line for research/);
  assert.match(html,/Last-known prices are research only/);
  assert.deepEqual(data,before); // Comparison never changes saved/slip selections.
  assert.equal(sameOffer({sportsbook:'FanDuel',line:2.5},{sportsbook:'FanDuel',line:2.5001}),false);
});

test('client time cannot keep a stale best price or stale slip estimate actionable', t => {
  t.mock.method(Date,'now',()=>now+31*60000);
  const data = fixture();
  const html = render(data);
  assert.match(html,/No current best price confirmed/);
  assert.doesNotMatch(html,/Best live price:|more profit per/);
  const pick = {game_time:gameTime,side:'over',selection:data.groups[0].best};
  const before = structuredClone(pick);
  assert.equal(getSelectionOdds(pick),null);
  assert.deepEqual(pick,before);
});

test('missing comparison, missing side and unavailable prices remain valid empty states', t => {
  t.mock.method(Date,'now',()=>now);
  assert.match(render(null),/Sportsbook comparison unavailable/);
  assert.match(render({...fixture(),groups:[]}),/No stored sportsbook offers/);
  assert.match(render(fixture(),'under'),/No current best price confirmed/);
  assert.doesNotMatch(render(fixture(),'under'),/Best live price:/);
});

test('a removed selected book never reuses its old live price after refresh', t => {
  t.mock.method(Date,'now',()=>now);
  const selected = fixture().groups[0].best;
  const prop = {sportsbook_offers:[]};
  const retained = retainedOffer(prop, selected);
  assert.equal(retained.sportsbook,'DraftKings');
  assert.equal(retained.line,2.5);
  assert.equal(retained.actionable,false);
  assert.equal(retained.odds,null);
  assert.equal(getSelectionOdds({game_time:gameTime, selection:retained}),null);
  assert.equal(selected.odds,120);
});

test('explicit unavailable states cannot enter estimates despite contradictory cached flags', t => {
  t.mock.method(Date,'now',()=>now);
  const selected=fixture().groups[0].best;
  for (const availability of ['last_known','expired','game_started','market_unavailable']) {
    assert.equal(getSelectionOdds({game_time:gameTime,selection:{...selected,availability,actionable:true}}),null);
  }
});
