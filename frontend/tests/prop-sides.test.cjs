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
    : nativeRequire(name);
  loaded.set(filename, mod);
  mod._compile(compiled, filename);
  return mod.exports;
}

const { getSideOdds } = loadTs("src/lib/propSides.ts");
const { useSlip } = loadTs("src/store/slip.ts");
const availability = { actionable: true, refreshed_at: new Date().toISOString(), expires_at: new Date(Date.now() + 6 * 3600000).toISOString() };
const baseProp = {
  game_time: new Date(Date.now() + 24 * 3600000).toISOString(),
  id: "prop-1", line: 24.5, sportsbook: "Primary",
  over_odds: -110, under_odds: -110,
  player: { id: "player-1", name: "Test Player" },
};

test("slip mutations wait for hydration and serialize changes to the same pick", () => {
  assert.equal(useSlip.getState().beginMutation("loading-pick"), false);
  useSlip.getState().finishLoading();
  assert.equal(useSlip.getState().beginMutation("loading-pick"), true);
  assert.equal(useSlip.getState().beginMutation("loading-pick"), false);
  useSlip.getState().endMutation("loading-pick");
  assert.equal(useSlip.getState().beginMutation("loading-pick"), true);
  useSlip.getState().endMutation("loading-pick");
});

test("missing primary-book Under stays unavailable despite legacy default", () => {
  const prop = { ...baseProp, sportsbook_offers: [
    { ...availability, sportsbook: "Primary", line: 24.5, over_odds: -105, under_odds: null },
    { ...availability, sportsbook: "Other", line: 24.5, over_odds: -115, under_odds: 120 },
  ] };
  assert.equal(getSideOdds(prop, "under"), null);
  assert.equal(getSideOdds(prop, "over"), -105);
});

test("odds match both the displayed sportsbook and line", () => {
  const offers = [
    { ...availability, sportsbook: "Other", line: 24.5, under_odds: 130 },
    { ...availability, sportsbook: "Primary", line: 25.5, under_odds: 125 },
  ];
  assert.equal(getSideOdds({ ...baseProp, sportsbook_offers: offers }, "under"), null);
  offers.push({ ...availability, sportsbook: "Primary", line: 24.5, under_odds: -120 });
  assert.equal(getSideOdds({ ...baseProp, sportsbook_offers: offers }, "under"), -120);
});

test("legacy odds without observed offers are unavailable and invalid prices are unavailable", () => {
  assert.equal(getSideOdds(baseProp, "under"), null);
  for (const under_odds of [null, undefined, 0, NaN, Infinity]) {
    assert.equal(getSideOdds({ ...baseProp, under_odds }, "under"), null);
  }
});

test("switching a slip side preserves one selection and other items", () => {
  useSlip.getState().initialize([]);
  useSlip.getState().addProp(baseProp, "over");
  useSlip.getState().addProp({ ...baseProp, id: "prop-2" }, "over");
  useSlip.getState().addProp(baseProp, "under");
  const items = useSlip.getState().items;
  assert.equal(items.length, 2);
  assert.equal(items.filter((item) => item.id === baseProp.id).length, 1);
  assert.equal(items.find((item) => item.id === baseProp.id).side, "under");
  assert.equal(items.find((item) => item.id === "prop-2").side, "over");
});

test("hydration replaces local selections and retains persisted Under", () => {
  useSlip.getState().initialize([{ ...baseProp, side: "under" }]);
  assert.equal(useSlip.getState().items.length, 1);
  assert.equal(useSlip.getState().items[0].side, "under");
  useSlip.getState().removeProp(baseProp.id);
  assert.deepEqual(useSlip.getState().items, []);
});

test("comparison renders both historical rates and disables unavailable Under", () => {
  const React = require("react");
  const { renderToStaticMarkup } = require("react-dom/server");
  const { PropSideComparison } = loadTs("src/components/PropSideComparison.tsx");
  const window = { hits: 3, decisions: 4 };
  const prop = { ...baseProp,
    sportsbook_offers: [{ ...availability, sportsbook: "Primary", line: 24.5, over_odds: -105, under_odds: null }],
    trends: { line: 24.5, average: 25, season: 2026, l5: window, l10: window, season_window: { hits: 0, decisions: 0 } },
  };
  const html = renderToStaticMarkup(React.createElement(PropSideComparison, {
    prop, selectedSide: "over", busy: false, onSelect() {},
  }));
  assert.match(html, /75%/);
  assert.match(html, /25%/);
  assert.match(html, /3\/4/);
  assert.match(html, /1\/4/);
  assert.match(html, /Pushes excluded/);
  assert.match(html, /aria-pressed="false" disabled=""/);
  assert.match(html, /Unavailable/);
  assert.doesNotMatch(html, /NaN|Infinity/);
});

test("late hydration preserves side changes, additions and removals while loading untouched picks", () => {
  const store = useSlip.getState();
  store.initialize([{ ...baseProp, side: "over" }]);
  store.addProp(baseProp, "under");
  store.addProp({ ...baseProp, id: "new" }, "under");
  store.removeProp("removed");
  store.initialize([
    { ...baseProp, side: "over" },
    { ...baseProp, id: "removed", side: "over" },
    { ...baseProp, id: "untouched", side: "over" },
  ], true);
  const items = useSlip.getState().items;
  assert.equal(items.length, 3);
  assert.equal(items.find((item) => item.id === baseProp.id).side, "under");
  assert.equal(items.find((item) => item.id === "new").side, "under");
  assert.ok(items.some((item) => item.id === "untouched"));
  assert.ok(!items.some((item) => item.id === "removed"));
});
