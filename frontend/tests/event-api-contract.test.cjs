const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const ts = require("typescript");

function loadApi() {
  const filename = path.resolve(__dirname, "../src/lib/api.ts");
  const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const mod = new Module(filename, module);
  mod.filename = filename;
  mod.paths = Module._nodeModulePaths(path.dirname(filename));
  mod._compile(compiled, filename);
  return mod.exports.api;
}

test("Event filters and detail preserve exact UUIDs while retaining legacy keys", async () => {
  const originalFetch = global.fetch;
  const requests = [];
  global.fetch = async (url) => {
    requests.push(new URL(url));
    return { ok: true, json: async () => ({}) };
  };
  try {
    const api = loadApi();
    const event_id = "6ff2324d-5dcb-455b-be37-2ad4dab5370a";
    await api.getFeed({ event_id });
    await api.getDiscover({ event_id });
    await api.getGame({ event_id, sport: "NBA" });
    await api.getGame("NBA|BOS|DET|2026-10-20");
    for (const request of requests.slice(0, 3)) {
      assert.equal(request.searchParams.get("event_id"), event_id);
      assert.equal(request.searchParams.has("game_key"), false);
    }
    assert.equal(requests[2].searchParams.get("sport"), "NBA");
    assert.equal(requests[3].searchParams.get("game_key"), "NBA|BOS|DET|2026-10-20");
  } finally {
    global.fetch = originalFetch;
  }
});

test("research requests an exact prop UUID without introducing legacy selection", async () => {
  const originalFetch = global.fetch;
  const requests = [];
  global.fetch = async (url) => {
    requests.push(new URL(url));
    return { ok: true, json: async () => ({}) };
  };
  try {
    const api = loadApi();
    await api.getPlayerResearch("player-one", { prop_id: "prop-one" });
    await api.getPlayerResearch("player-one", { prop_type: "points", line: 0 });
    assert.equal(requests[0].pathname, "/players/player-one/research");
    assert.equal(requests[0].searchParams.get("prop_id"), "prop-one");
    assert.equal(requests[0].searchParams.has("line"), false);
    assert.equal(requests[0].searchParams.has("prop_type"), false);
    assert.equal(requests[1].searchParams.get("prop_type"), "points");
    assert.equal(requests[1].searchParams.get("line"), "0");
  } finally {
    global.fetch = originalFetch;
  }
});
