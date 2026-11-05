const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");
function load(relative) {
  const filename = path.resolve(__dirname, "../src/lib", relative + ".ts");
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  mod.require = (name) => load(name.replace("./", ""));
  mod._compile(ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText, filename);
  return mod.exports;
}
const { americanToDecimal, decimalToAmerican, calculateParlay, groupBySportsbook } = load("parlay");
const pick = (id, odds, book = "Book A") => ({
  game_time: new Date(Date.now() + 24 * 3600000).toISOString(),
  id, player: { sport: "NBA", team_abbr: "BOS" }, odds_event_id: id,
  sportsbook: "Primary", line: 10, side: "under", under_odds: -110,
  selection: { sportsbook: book, line: 12, odds, actionable: true, provider_observed_at: new Date().toISOString(), expires_at: new Date(Date.now() + 6 * 3600000).toISOString() },
});
test("American conversion supports positive, negative and even money", () => {
  assert.equal(americanToDecimal(150), 2.5);
  assert.equal(americanToDecimal(-200), 1.5);
  assert.equal(decimalToAmerican(1.5), -200);
  assert.equal(decimalToAmerican(2), 100);
  for (const odds of [0, 99, -99, NaN, Infinity]) assert.equal(americanToDecimal(odds), null);
});
test("two -110 legs multiply unrounded decimal odds for return and profit", () => {
  const result = calculateParlay([pick("a", -110), pick("b", -110)], 10);
  assert.equal(result.reason, null);
  assert.equal(result.american, 264);
  assert.ok(Math.abs(result.payout - 36.44628099173554) < 1e-9);
  assert.ok(Math.abs(result.profit - 26.44628099173554) < 1e-9);
});
test("uses selected sportsbook odds and handles a single bet", () => {
  const result = calculateParlay([pick("a", 150)], 20);
  assert.equal(result.payout, 50);
  assert.equal(result.profit, 30);
});
test("never combines prices across books", () => {
  const items = [pick("a", 100), pick("b", 200, "Book B")];
  assert.match(calculateParlay(items, 10).reason, /one sportsbook/);
  assert.deepEqual(groupBySportsbook(items).map(([book, picks]) => [book, picks.length]), [["Book A", 1], ["Book B", 1]]);
});
test("same event requires sportsbook pricing and unavailable selections do not fallback", () => {
  assert.match(calculateParlay([pick("a", 100), pick("a", 200)], 10).reason, /Same-game/);
  assert.match(calculateParlay([pick("a", null)], 10).reason, /unavailable/);
});
test("ambiguous matchup names and partial event IDs cannot bypass same-game checks", () => {
  const a = { ...pick("a", 100), odds_event_id: null, game_time: new Date(Date.now() + 3600000).toISOString(), opponent: "NYK" };
  const b = { ...a, id: "b", player: { sport: "NBA", team_abbr: "NYK" }, opponent: "BOS", game_time: a.game_time };
  assert.match(calculateParlay([a, b], 10).reason, /Event details/);
  assert.match(calculateParlay([{ ...a, odds_event_id: "provider-id" }, b], 10).reason, /Event details/);
});
test("missing event identity, invalid stakes and extreme payouts fail safely", () => {
  assert.match(calculateParlay([{ ...pick("a", 100), odds_event_id: null }, pick("b", 100)], 10).reason, /Event details/);
  for (const stake of [0, -1, NaN, Infinity]) assert.ok(calculateParlay([pick("a", 100)], stake).reason);
  assert.match(calculateParlay([pick("a", 100)], Number.MAX_VALUE).reason, /limit/);
});
