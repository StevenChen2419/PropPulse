const test = require('node:test');
const assert = require('node:assert/strict');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { loadSource } = require('./load-source.cjs');
const { SelectionPrice } = loadSource('components/SelectionPrice.tsx');
const { useSavedProps, savedSelectionKey } = loadSource('store/savedProps.ts');
const { useSlip } = loadSource('store/slip.ts');
const now = Date.parse('2026-10-22T18:00:00Z');
const offer = { sportsbook:'FanDuel', line:20.5, odds:120, original_odds:-110,
  price_change:'improved', actionable:true, availability:'available',
  original_observed_at:'2026-10-22T17:50:00Z',provider_observed_at:'2026-10-22T17:59:00Z',expires_at:'2026-10-22T23:59:00Z' };
const render = selection => renderToStaticMarkup(React.createElement(SelectionPrice,{ selection,gameTime:'2026-10-23T18:00:00Z' }));

test('original and latest evidence display independently; expired prices cannot appear current', t => {
  t.mock.method(Date,'now',()=>now);
  const html=render(offer);
  assert.match(html,/Originally selected: -110/); assert.match(html,/Latest observed: \+120 · improved/);
  assert.match(html,/Original observation:.*ET/); assert.match(html,/Latest observation:.*ET/);
  assert.match(html,/Actionable/);
  assert.match(render({...offer,original_odds:null,price_change:null}),/Original price unavailable\./);
  const missing=render({...offer,odds:null,availability:'market_unavailable',actionable:false});
  assert.match(missing,/Current price unavailable\./); assert.doesNotMatch(missing,/improved/);
  t.mock.method(Date,'now',()=>now+7*3600000);
  assert.match(render(offer),/Current price unavailable\./);
  assert.match(render(offer),/Excluded from estimates/);
});

test('bookmarks and exact keys coexist without conflating lines, sides or sportsbooks', () => {
  const store=useSavedProps.getState();
  store.setIds(['prop']);
  store.setExact([{id:'saved',prop_id:'prop',side:'under',selection:offer}]);
  const key=savedSelectionKey('prop','under',offer);
  assert.equal(useSavedProps.getState().exact[key],'saved');
  for(const [side,selection] of [['over',offer],['under',{...offer,line:21.5}],['under',{...offer,sportsbook:'DraftKings'}]])
    assert.equal(useSavedProps.getState().exact[savedSelectionKey('prop',side,selection)],undefined);
  store.removeExact(key);
  assert.equal(useSavedProps.getState().ids.prop,true);
});

test('slip edit keeps one stable prop identity, other selections and original evidence on refresh', () => {
  useSlip.getState().initialize([{id:'prop',side:'over',selection:offer},{id:'other',side:'under'}]);
  useSlip.getState().finishLoading();
  assert.equal(useSlip.getState().beginMutation('prop'),true);
  assert.equal(useSlip.getState().beginMutation('prop'),false);
  const next={...offer,sportsbook:'DraftKings',line:21.5,original_odds:130,odds:130};
  useSlip.getState().addProp({id:'prop'},'under',next);
  useSlip.getState().endMutation('prop');
  useSlip.getState().initialize([{id:'prop',side:'over',selection:offer},{id:'other',side:'under'}],true);
  assert.equal(useSlip.getState().items.length,2);
  assert.deepEqual(useSlip.getState().items.find(p=>p.id==='prop').selection,next);
  useSlip.getState().refreshAvailability([]);
  const kept=useSlip.getState().items.find(p=>p.id==='prop');
  assert.equal(kept.selection.original_odds,130); assert.equal(kept.selection.sportsbook,'DraftKings');
  assert.equal(kept.selection.odds,null);
});

test('late saved hydration cannot undo a completed exact save or resurrect an unsave', () => {
  const store=useSavedProps.getState(), key=savedSelectionKey('prop','over',offer);
  const row={id:'saved',prop_id:'prop',side:'over',selection:offer};
  store.setExact([]); store.addExact(key,'saved'); store.setExact([],true);
  assert.equal(useSavedProps.getState().exact[key],'saved');
  store.removeExact(key); store.setExact([row],true);
  assert.equal(useSavedProps.getState().exact[key],undefined);
});

test('exact save/edit APIs send identity only and use authenticated shared request flow', async t => {
  const calls=[];
  t.mock.method(global,'fetch',async (url,options)=>{if(url.endsWith('/auth/csrf'))return {ok:true,json:async()=>({csrf_token:'fixture-proof'})};calls.push({url,options});return {ok:true,json:async()=>({id:'saved'})};});
  const {api}=loadSource('lib/api.ts');
  await api.saveSelection('prop','under',offer);
  await api.editSlipSelection('prop','under',offer);
  await api.deleteSavedSelection('saved');
  assert.deepEqual(JSON.parse(calls[0].options.body),{sportsbook:'FanDuel',line:20.5,side:'under'});
  assert.equal(calls[1].options.method,'PATCH'); assert.match(calls[1].url,/\/me\/slip\/items\/prop$/);
  assert.equal(calls[2].options.method,'DELETE');
  for(const {options} of calls){assert.equal(options.credentials,'include');assert.equal(options.headers['X-CSRF-Token'],'fixture-proof');assert.equal(options.headers.Authorization,undefined);}
});
