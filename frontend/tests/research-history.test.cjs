const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function load(relative, mocks = {}) {
  const filename = path.resolve(__dirname, "../src", relative);
  const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    fileName: filename,
  }).outputText;
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  const nativeRequire = mod.require.bind(mod);
  mod.require = (name) => {
    if (name in mocks) return mocks[name];
    if (name.startsWith("@/")) {
      const relative = name.slice(2);
      return load(`${relative}${fs.existsSync(path.resolve(__dirname, "../src", `${relative}.ts`)) ? ".ts" : ".tsx"}`, mocks);
    }
    if (name === "./ResearchHistorySummary") return load("components/ResearchHistorySummary.tsx", mocks);
    return nativeRequire(name);
  };
  mod._compile(compiled, filename);
  return mod.exports;
}

const history = {
  status: "available", stored_games: 12, valid_market_games: 10, eligible_games: 8,
  current_season_games: 0, previous_season_games: 8, selected_season: 2026,
  excluded_counts: {}, insufficient_l5: false, insufficient_l10: true,
  competition_scope: "Provider history excluding preseason; regular season and playoffs are not separately identified.",
};
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));

test("empty history states distinguish absent rows, missing market statistics, and excluded results", () => {
  const { PlayerResearchChart } = load("components/PlayerResearchChart.tsx");
  const chart = (status) => render(PlayerResearchChart, { games: [], line: 20.5, propType: "points", history: { ...history, status } });
  assert.match(chart("no_history"), /No stored game history/);
  assert.match(chart("no_valid_market_statistics"), /no valid statistics for this market/);
  assert.match(chart("excluded_history"), /none qualify as completed results before/);
  assert.match(render(PlayerResearchChart, { games: [], line: 20.5, propType: "points" }), /No eligible historical results/);
});

test("research windows disclose mixed seasons, short samples, and an empty selected season", () => {
  const { ResearchHistorySummary, HistoricalTrendSummary } = load("components/ResearchHistorySummary.tsx");
  const summary = render(ResearchHistorySummary, { history });
  assert.match(summary, /0 in the 2026 season/);
  assert.match(summary, /previous seasons/);
  assert.match(summary, /fewer than 10 eligible results/);
  assert.match(summary, /not predictions/);
  assert.match(summary, /excluding preseason/);
  const mixed = render(HistoricalTrendSummary, { label: "Last 5", window: {
    games: 5, decisions: 4, hits: 3, pushes: 1, hit_rate: 0.75,
    seasons: [2026, 2025], season_scope: "mixed_seasons",
  } });
  assert.match(mixed, /3\/4 hits · 5 games/);
  assert.match(mixed, /Across seasons \(2026, 2025\)/);
  const empty = render(HistoricalTrendSummary, { label: "2026 season", window: {
    games: 0, decisions: 0, hits: 0, pushes: 0, hit_rate: null, seasons: [], season_scope: "empty",
  } });
  assert.match(empty, /No eligible results/);
  assert.doesNotMatch(empty, /0%/);
  assert.equal(render(ResearchHistorySummary, {}), "");
});

test("selected offer availability and line movement remain visible without trends", () => {
  const selected = {
    id: "prop-one", prop_type: "points", line: 20.5, over_odds: -110, under_odds: -105,
    sportsbook: "Book One", sportsbook_count: 1, opponent: "DET", is_home: false,
    game_time: "2099-10-15T23:00:00Z", actionable: true, availability: "available",
    provider_observed_at: new Date().toISOString(),
  };
  const research = {
    selected_prop: selected, available_props: [selected], trends: null, games: [], splits: null,
    history: { ...history, status: "no_history", eligible_games: 0, previous_season_games: 0 },
    line_movement: { sportsbook: "Book One", snapshot_count: 2, opening_line: 19.5, current_line: 20.5,
      line_change: 1, opened_at: "2026-10-14T10:00:00Z", updated_at: "2026-10-14T11:00:00Z",
      opening_over_odds: -110, opening_under_odds: -110, current_over_odds: -110, current_under_odds: -105 },
  };
  const states = [{ id: "player-one", name: "Test Player", sport: "NBA", team_abbr: "BOS", props: [] }, null, { scope: ":", data: research }, null, false, false, false, null, null];
  const { default: PlayerPage } = load("app/player/[id]/page.tsx", {
    react: { ...React, useState: () => [states.shift(), () => {}], useEffect: () => {}, useCallback: (fn) => fn, useMemo: (fn) => fn() },
    "next/navigation": { useParams: () => ({ id: "player-one" }), useSearchParams: () => new URLSearchParams(), useRouter: () => ({ back() {}, replace() {}, push() {} }) },
    "@/lib/useLiveRefresh": { useLiveRefresh() {} },
    "@/lib/useOfferClock": { useOfferClock() {} },
    "@/lib/api": { api: {} },
    "@/lib/propSides": { availabilityLabel: () => "Live", isActionable: () => true,
      offerObservation: offer => offer.provider_observed_at ?? offer.refreshed_at },
  });
  const html = render(PlayerPage, {});
  assert.match(html, /Best exact-line odds/);
  assert.match(html, /Over -110/);
  assert.match(html, /Line Movement/);
  assert.match(html, /Book One \/ 2 snapshots/);
  assert.match(html, /No stored game history/);
  assert.doesNotMatch(html, /Eligible history average/);
});

test("shared prop comparison discloses previous and mixed seasons with real sample counts", () => {
  const { PropSideComparison } = load("components/PropSideComparison.tsx");
  const window = { games: 5, decisions: 5, hits: 3, pushes: 0, hit_rate: 0.6, seasons: [2025], season_scope: "previous_seasons" };
  const prop = { id: "one", player: { name: "Test Player" }, line: 20.5, sportsbook: "Book", trends: {
    line: 20.5, season: 2026, average: 21, l5: window,
    competition_scope: history.competition_scope,
    l10: { ...window, games: 8, seasons: [2025, 2026], season_scope: "mixed_seasons" },
    season_window: { ...window, games: 3, seasons: [2026], season_scope: "current_season" },
  } };
  const html = render(PropSideComparison, { prop, selectedSide: "over", busy: false, onSelect() {} });
  assert.match(html, /L5 · 5 games/);
  assert.match(html, /Previous seasons \(2025\)/);
  assert.match(html, /L10 · 8 games/);
  assert.match(html, /Across seasons \(2025, 2026\)/);
  assert.match(html, /2026 · 3 games/);
  assert.match(html, /Eligible history avg/);
  assert.match(html, /Not predictions/);
  assert.match(html, /excluding preseason; regular season and playoffs are not separately identified/);
});

test("history exclusions explain date and completion filtering with bounded labels", () => {
  const { ResearchHistorySummary } = load("components/ResearchHistorySummary.tsx");
  const html = render(ResearchHistorySummary, { history: { ...history, excluded_counts: {
    at_or_after_prop: 2, future_game: 1, completion_unknown_today: 3, missing_statistic: 4,
    invalid_date: 1, not_completed: 2, private_provider_detail: 5, another_unknown_reason: 1,
    duplicate_game: 0,
  } } });
  assert.match(html, /At or after the selected game&#x27;s start: 2/);
  assert.match(html, /Future game: 1/);
  assert.match(html, /Same-day completion unconfirmed: 3/);
  assert.match(html, /Missing market statistic: 4/);
  assert.match(html, /Invalid game date: 1/);
  assert.match(html, /Game not completed: 2/);
  assert.match(html, /Other eligibility exclusions: 6/);
  assert.doesNotMatch(html, /private_provider_detail|another_unknown_reason|Duplicate game/);
});
