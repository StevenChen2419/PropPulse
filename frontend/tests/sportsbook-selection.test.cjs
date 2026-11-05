const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");

// Load actual project modules without emitting files or adding a test dependency.
const loaded = new Map();
function loadTs(relativePath) {
  const filename = path.resolve(__dirname, "..", relativePath);
  if (loaded.has(filename)) return loaded.get(filename).exports;
  const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
    },
    fileName: filename,
  }).outputText;
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const nativeRequire = mod.require.bind(mod);
  mod.require = (name) => name.startsWith("@/")
    ? loadTs(`src/${name.slice(2)}.ts`)
    : name.startsWith("./") ? loadTs(path.resolve(path.dirname(filename), `${name}.ts`))
    : nativeRequire(name);
  loaded.set(filename, mod);
  mod._compile(compiled, filename);
  return mod.exports;
}


const availability = { actionable: true, refreshed_at: new Date().toISOString(), expires_at: new Date(Date.now() + 6 * 3600000).toISOString() };
const game_time = new Date(Date.now() + 24 * 3600000).toISOString();
const { getSideOffers, chooseOffer, getSelectionOdds, sameOffer } = loadTs("src/lib/propSides.ts");
const { useSlip } = loadTs("src/store/slip.ts");
test("same-game calculator shows approximation disclosure and waits for correlated pricing", () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const { ParlayCalculator, hasSameGamePicks } = loadTs("src/components/ParlayCalculator.tsx");
  const first = { game_time, id: "a", player: { sport: "NBA" }, odds_event_id: "game", side: "over",
    sportsbook: "Book", line: 10.5, selection: { ...availability, sportsbook: "Book", line: 10.5, odds: -110 } };
  const second = { ...first, id: "b" };
  assert.equal(hasSameGamePicks([first, second]), true);
  assert.equal(hasSameGamePicks([first, { ...second, player: { sport: "NFL" } }]), false);
  const html = renderToStaticMarkup(React.createElement(ParlayCalculator, { items: [first, second], busy: false }));
  assert.match(html, /Same-game estimate/);
  assert.match(html, /Not a sportsbook quote/);
  assert.match(html, /Calculating correlation estimate/);
  assert.match(html, /Assumed correlation/);
  assert.doesNotMatch(html, /\+264/);
  const separate = renderToStaticMarkup(React.createElement(ParlayCalculator, {
    items: [first, { ...second, odds_event_id: "other-game" }], busy: false,
  }));
  assert.match(separate, /\+264/);
  assert.doesNotMatch(separate, /Same-game estimate/);
});
const prop = { game_time, id: "pick", player: {name: "Player"}, sportsbook: "Primary", line: 24.5, over_odds: -110, under_odds: -110,
  sportsbook_offers: [
    {...availability, sportsbook: "Primary", line: 24.5, over_odds: -110, under_odds: null},
    {...availability, sportsbook: "Other", line: 25.5, over_odds: 120, under_odds: -120},
    {...availability, sportsbook: "Other", line: 24.5, over_odds: 110, under_odds: null},
  ] };
test("offer choices honor exact side, sportsbook and line", () => {
  assert.equal(getSideOffers(prop, "under").length, 1);
  assert.equal(chooseOffer(prop, "over").sportsbook, "Primary");
  assert.equal(chooseOffer(prop, "under").sportsbook, "Other");
  const chosen = chooseOffer(prop, "over", {...availability, sportsbook: "Other", line: 25.5});
  assert.equal(chosen.odds, 120);
  assert.equal(sameOffer(chosen, {...availability, sportsbook: "Other", line: 24.5}), false);
});
test("invalid American prices cannot be selected from either offers or legacy props", () => {
  const { getSideOdds } = loadTs("src/lib/propSides.ts");
  for (const price of [-99, -1, 0, 1, 99, NaN, Infinity]) {
    const invalid = {...prop, over_odds: price, sportsbook_offers: []};
    assert.deepEqual(getSideOffers(invalid, "over"), []);
    assert.equal(getSideOdds(invalid, "over"), null);
    assert.deepEqual(getSideOffers({...invalid, sportsbook_offers: [{...availability, sportsbook: "Other", line: 25.5, over_odds: price}]}, "over"), []);
  }
});
test("saved selection uses its own price and never falls back from unavailable", () => {
  assert.equal(getSelectionOdds({...prop, side: "over", selection: {...availability, sportsbook: "Other", line: 25.5, odds: 120}}), 120);
  assert.equal(getSelectionOdds({...prop, side: "over", selection: {...availability, sportsbook: "Other", line: 25.5, odds: null}}), null);
  assert.equal(getSelectionOdds({...prop, side: "over"}), null);
});
test("replacing sportsbook keeps one pick, hydration and rollback preserve selection", () => {
  const store=useSlip.getState();
  const first={...availability, sportsbook: "Other", line: 25.5, odds: 120};
  store.initialize([{...prop, side: "over", selection: first}]);
  const previous=useSlip.getState().items[0];
  store.addProp(prop,"over",{...availability, sportsbook: "Other",line:24.5,odds:110});
  assert.equal(useSlip.getState().items.length,1);
  assert.equal(useSlip.getState().items[0].selection.line,24.5);
  store.addProp(previous,previous.side,previous.selection);
  assert.deepEqual(useSlip.getState().items[0].selection,first);
});
test("comparison shows selected book and line without original-line history", () => {
  const React=require("react");
  const {renderToStaticMarkup}=require("react-dom/server");
  const {PropSideComparison}=loadTs("src/components/PropSideComparison.tsx");
  const html=renderToStaticMarkup(React.createElement(PropSideComparison, {
    prop:{...prop,trends:{line:24.5}}, selectedSide:"over", busy:false,
    selection:{...availability, sportsbook:"Other",line:25.5,odds:120}, onSelect(){}
  }));
  assert.match(html,/25.5/);
  assert.match(html,/Other/);
  assert.match(html,/\+120/);
  assert.doesNotMatch(html,/History at/);
});
test("interaction sends selected book and line, without trusting client odds", async () => {
  const {api}=loadTs("src/lib/api.ts");
  const previous=global.fetch;
  let body;
  const authoritative = {...availability, sportsbook:"Other",line:25.5,odds:-135};
  global.fetch=async (_url,options)=>{if(_url.endsWith("/auth/csrf"))return {ok:true,json:async()=>({csrf_token:"fixture-proof"})};body=JSON.parse(options.body);return {ok:true,json:async()=>({ok:true,selection:authoritative})};};
  try {
    const result = await api.interact("pick","add_to_slip","under",{...availability, sportsbook:"Other",line:25.5,odds:-120});
    assert.deepEqual(body,{action:"add_to_slip",side:"under",sportsbook:"Other",line:25.5});
    assert.deepEqual(result.selection, authoritative);
  } finally {global.fetch=previous;}
});


test("expired and started selections block payout and retain identity", () => {
  const { calculateParlay } = loadTs("src/lib/parlay.ts");
  const selection = { ...availability, sportsbook: "Other", line: 25.5, odds: 120,
    expires_at: new Date(Date.now() - 1).toISOString() };
  const item = { ...prop, side: "over", selection };
  assert.equal(getSelectionOdds(item), null);
  assert.match(calculateParlay([item], 10).reason, /unavailable/);
  assert.equal(item.selection.line, 25.5);
  const started = { ...item, selection: { ...selection, ...availability }, game_time: new Date(Date.now() - 1).toISOString() };
  assert.equal(getSelectionOdds(started), null);
});

test("missing preferred offer never substitutes a different line or sportsbook", () => {
  assert.equal(chooseOffer(prop, "over", { sportsbook: "Gone", line: 24.5 }), undefined);
  assert.equal(chooseOffer(prop, "over", { sportsbook: "Other", line: 26.5 }), undefined);
});

test("cached observations display Last known and unavailable SGP skips calculation", () => {
  const { availabilityLabel } = loadTs("src/lib/propSides.ts");
  assert.equal(availabilityLabel({ ...availability, refreshed_at: new Date(Date.now() - 31 * 60000).toISOString() }, game_time), "Last known odds");
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const { ParlayCalculator } = loadTs("src/components/ParlayCalculator.tsx");
  const item = { ...prop, odds_event_id: "same", player: { sport: "NBA" }, side: "over",
    selection: { ...availability, sportsbook: "Other", line: 25.5, odds: 120, actionable: false } };
  const html = renderToStaticMarkup(React.createElement(ParlayCalculator, { items: [item, { ...item, id: "second" }], busy: false }));
  assert.match(html, /selected offer is unavailable/);
  assert.doesNotMatch(html, /Calculating correlation estimate|Estimated profit/);
});


test("availability refresh preserves changed identities and pending selections", () => {
  const store = useSlip.getState();
  const item = { ...prop, side: "over", selection: { ...availability, sportsbook: "Other", line: 25.5, odds: 120 } };
  store.initialize([item]);
  store.refreshAvailability([{ ...item, selection: { ...item.selection, actionable: false, odds: null } }]);
  assert.equal(getSelectionOdds(useSlip.getState().items[0]), null);
  assert.equal(useSlip.getState().items[0].selection.line, 25.5);
  store.initialize([item]);
  store.finishLoading();
  store.beginMutation(item.id);
  store.refreshAvailability([]);
  assert.equal(useSlip.getState().items[0].selection.odds, 120);
  store.endMutation(item.id);
  store.removeProp(item.id);
  store.refreshAvailability([item]);
  assert.deepEqual(useSlip.getState().items, []);
});
test('unavailable selected comparison keeps its line and offers an explicit other side', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { PropSideComparison } = loadTs('src/components/PropSideComparison.tsx');
  const html = renderToStaticMarkup(React.createElement(PropSideComparison, {
    prop: { ...prop, player: { name: 'Fixture player' } }, selectedSide: 'under',
    selection: { sportsbook: 'Gone', line: 19.5, odds: null, actionable: false }, busy: false, onSelect() {},
  }));
  const buttons = [...html.matchAll(/<button\b[\s\S]*?<\/button>/g)].map(match => match[0]);
  assert.equal(buttons.length, 2);
  assert.doesNotMatch(buttons[0], / disabled=/);
  assert.match(buttons[1], / disabled=/);
  assert.match(buttons[1], />19\.5</);
  assert.match(buttons[1], /Unavailable/);
});
