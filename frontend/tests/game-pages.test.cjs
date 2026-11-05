const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");

function load(relative, mocks) {
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
      return load(`${relative}${fs.existsSync(path.resolve(__dirname, "../src", relative + ".tsx")) ? ".tsx" : ".ts"}`, mocks);
    }
    return nativeRequire(name);
  };
  mod._compile(compiled, filename);
  return mod.exports;
}

const eventId = "6ff2324d-5dcb-455b-be37-2ad4dab5370a";
const game = {
  event_id: eventId, identity_source: "authoritative", game_key: "NBA|2099-10-20|BOS|DET",
  sport: "NBA", away_team: "Boston Celtics", home_team: "Detroit Pistons",
  scheduled_start_at: "2099-10-20T19:00:00Z", game_time: "2099-10-20T19:00:00Z",
  source: "unavailable", prop_count: 0, has_eligible_props: false,
};

function renderPage(file, states, query = '') {
  const mocks = {
    react: { ...React, useState: () => [states.shift(), () => {}], useEffect() {}, useMemo: (fn) => fn(), useCallback: (fn) => fn, useRef: (value) => ({ current: value }) },
    "next/link": { __esModule: true, default: ({ children, ...props }) => React.createElement("a", props, children) },
    "next/navigation": { useParams: () => ({ gameKey: eventId }), useSearchParams: () => new URLSearchParams(query), useRouter: () => ({ push() {} }) },
    "@/lib/useLiveRefresh": { useLiveRefresh() {} },
    "@/lib/useOfferClock": { useOfferClock() {} },
    "@/components/PropCard": { PropCard: () => null },
    "@/components/FeedFilters": { FeedFilters: () => null },
  };
  return renderToStaticMarkup(React.createElement(load(file, mocks).default));
}

test("board game links use canonical UUIDs and disclose compatibility game context", () => {
  const legacy = { ...game, event_id: null, identity_source: "legacy", game_key: "NBA|2099-10-21|BOS|DET" };
  const html = renderPage("app/page.tsx", [[], [game, legacy], 0, false, null, "", "", false, null, null, false]);
  assert.match(html, new RegExp(`href="/games/${eventId}"`));
  assert.match(html, /href="\/games\/NBA%7C2099-10-21%7CBOS%7CDET"/);
  assert.match(html, /Upcoming Games/);
  assert.match(html, /Legacy|Unverified|unverified/);
});

test("empty authoritative game detail retains participants and schedule", () => {
  const html = renderPage("app/games/[gameKey]/page.tsx", [{ ...game, total_props: 0, sportsbook_count: 0, props: [] }, false, null, 0]);
  assert.match(html, /Boston Celtics.*Detroit Pistons/);
  assert.match(html, /Oct 20/);
  assert.match(html, /Odds unavailable for this game/);
  assert.doesNotMatch(html, /Could not load game/);
});

test("Discover retains an unavailable selected Event option with its stable value", () => {
  const html = renderPage("app/discover/page.tsx", ["", { props: [], total: 0 }, [game], false, null], `sport=NBA&event_id=${eventId}`);
  assert.match(html, new RegExp(`value="event:${eventId}" selected`));
  assert.match(html, /Odds unavailable/);
  assert.match(html, /Boston Celtics.*Detroit Pistons/);
});
