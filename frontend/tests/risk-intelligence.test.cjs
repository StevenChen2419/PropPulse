const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function renderPanel(data, loading = false, error = null) {
  const filename = path.resolve(__dirname, "../src/components/SportRiskIntelligence.tsx");
  const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    fileName: filename,
  }).outputText;
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const nativeRequire = mod.require.bind(mod);
  const states = ["All", 0, data, loading, error];
  mod.require = (name) => {
    if (name === "react") return { ...React, useState: () => [states.shift(), () => {}], useEffect: () => {} };
    if (name === "@/lib/useLiveRefresh") return { useLiveRefresh: () => {} };
    if (name === "@/lib/api") return { api: {} };
    return nativeRequire(name);
  };
  mod._compile(compiled, filename);
  return renderToStaticMarkup(React.createElement(mod.exports.default));
}

test("risk panel distinguishes unknown history from an assessed zero score across sports", () => {
  const base = {
    label: "Low", method: "sport_workload", reasons: ["Recent workload is light"], missing_data: [],
    games_in_7d: 0, workload: { label: "Recent workload", value: 0, unit: "minutes" }, next_game: null,
  };
  const html = renderPanel({
    sports: ["NBA", "WNBA", "MLB", "NFL", "NHL"].map((sport) => ({ sport, active_players: 0, assessed_players: 0, status: "no_upcoming_games", description: "No upcoming games available" })),
    players: [
      { ...base, player: { id: "one", name: "Known Player", team_abbr: "ABC", sport: "WNBA" }, score: 0 },
      { ...base, player: { id: "two", name: "Unknown Player", team_abbr: "DEF", sport: "NFL" }, score: null, label: "Unknown", games_in_7d: null, workload: { label: "Snaps", value: null, unit: "snaps" }, missing_data: ["Recent history unavailable"] },
    ], generated_at: "2026-09-07T12:00:00Z",
  });
  assert.match(html, /0\/100/);
  assert.match(html, /Not assessed/);
  assert.match(html, /Recent history unavailable/);
  assert.match(html, /not injury or betting outcome probabilities/);
  assert.match(html, /href="\/player\/two"/);
  assert.match(html, /No upcoming games available/);
  assert.doesNotMatch(html, /0%/);
  for (const sport of ["NBA", "WNBA", "MLB", "NFL", "NHL"]) assert.ok(html.includes(sport));
});

test("risk panel provides independent loading and retry states", () => {
  assert.match(renderPanel(null, true), /Loading all sports risk intelligence/);
  const html = renderPanel(null, false, "Temporary failure");
  assert.match(html, /role="alert"/);
  assert.match(html, /Temporary failure/);
  assert.match(html, /Try again/);
});
