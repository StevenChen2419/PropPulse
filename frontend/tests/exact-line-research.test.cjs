const test = require('node:test');
const assert = require('node:assert/strict');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { loadSource } = require('./load-source.cjs');
const fixtures = require('./fixtures/exact-line-research.json');
const wrapper = ({children}) => React.createElement('div', null, children);
const charts = Object.fromEntries(['Bar','CartesianGrid','Cell','ResponsiveContainer','Tooltip','XAxis','YAxis','Line'].map(key => [key,wrapper]));
charts.ComposedChart = ({data,children}) => React.createElement('div', {'data-values':JSON.stringify(data)},children);
charts.ReferenceLine = ({y}) => React.createElement('div', {'data-reference-line':y});
const { ExactLinePanel } = loadSource('components/ExactLinePanel.tsx',{recharts:charts});
const render = data => renderToStaticMarkup(React.createElement(ExactLinePanel,{data,gameTime:'2099-01-01T00:00:00Z',onSelection(){}}));

test('all normalized sports and roles show actual outcomes, samples, provenance and line reference', () => {
  for (const fixture of fixtures) {
    const html=render(fixture.exact);
    for (const text of [/Exact-line research/,/4 appearances/,/3 valid outcomes/,/1 missing/,/Settled rate \(pushes excluded\)/,
      /Opponent ID/,/Source coverage uncertain/,/Invented offline fixture/]) assert.match(html,text);
    assert.match(html,new RegExp(`data-reference-line="${fixture.exact.line}"`));
    assert.match(html,/Over|over/);assert.match(html,/Under|under/);assert.match(html,/Push|push/);
    assert.match(html,/Expired odds/);
  }
});
test('whole line pushes are not wins and Under alternate line uses its own response', () => {
  const whole=fixtures.find(f=>f.sport==='WNBA'&&f.exact.line===2).exact;
  const alternate=fixtures.find(f=>f.sport==='WNBA'&&f.exact.line===2.5).exact;
  assert.match(render(whole),/over hits: 1\/3 valid outcomes · 33.3%/);
  assert.match(render(whole),/1 losses · 1 pushes · 1 missing/);
  assert.match(render(alternate),/DraftKings · under 2.5/);
  assert.match(render(alternate),/under hits: 2\/3 valid outcomes · 66.7%/);
});
test('unsupported, empty and missing states explain unavailable evidence without percentages', () => {
  const data=structuredClone(fixtures[0].exact);
  data.status='unsupported_market';data.games=[];
  for(const key of ['l5','l10','season_window']) data[key]={appearances:0,valid_samples:0,missing_samples:0,hits:0,losses:0,pushes:0,over_hits:0,under_hits:0,raw_hit_rate:null,settled_decisions:0,settled_hit_rate:null};
  assert.match(render(data),/No trustworthy statistic mapping/);
  assert.doesNotMatch(render(data),/0.0%/);
  data.status='no_recorded_games';assert.match(render(data),/No eligible completed games/);
  data.status='missing_metric';assert.match(render(data),/no complete values/);
});
test('exact research links preserve player/Prop identity, side, sportsbook and alternate line', () => {
  const { propResearchHref }=loadSource('lib/gameNavigation.ts');
  const href=propResearchHref('player','prop',{sportsbook:'DraftKings',line:2.5,side:'under'});
  assert.equal(href,'/player/player?prop_id=prop&sportsbook=DraftKings&offer_line=2.5&side=under');
});
