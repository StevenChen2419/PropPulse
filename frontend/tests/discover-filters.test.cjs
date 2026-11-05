const test = require('node:test');
const assert = require('node:assert/strict');
const { loadSource } = require('./load-source.cjs');
const { readDiscoverFilters, discoverURL, DISCOVER_PAGE_SIZE } = loadSource('lib/discoverFilters.ts');
const read = value => readDiscoverFilters(new URLSearchParams(value));

test('Discover round trips shareable filters and pagination with canonical sport/market keys', () => {
  const filters = read('sport=nhl&market=shots_on_goal&search=++McDavid++Edmonton+&sportsbook=FanDuel&availability=last_known&sort=over_desc&game_date=2026-10-21&page=3');
  assert.equal(filters.sport, 'NHL'); assert.equal(filters.search, 'McDavid Edmonton');
  assert.equal(filters.page, 3); assert.equal(DISCOVER_PAGE_SIZE, 24);
  assert.deepEqual(read(discoverURL(filters).split('?')[1]), filters);
  assert.equal(discoverURL(read('')), '/discover');
});

test('invalid query values fail gracefully without changing subject identity', () => {
  const filters = read('sport=unknown&market=bad%25&sort=hit_rate&availability=expired&game_date=2026-02-30&page=-2&event_id=bad');
  assert.deepEqual(filters, read(''));
  for (const page of ['NaN', '1.5', '100000000']) assert.equal(read(`page=${page}`).page, 1);
  assert.equal(read(`search=${'a'.repeat(300)}`).search.length, 120);
});

test('filter updates reset pages while navigation restores the previous view', () => {
  const original = read('sport=NHL&search=Connor&page=4&sort=player');
  const updated = { ...original, sportsbook: 'FanDuel', page: 1 };
  assert.equal(read(discoverURL(updated).split('?')[1]).page, 1);
  // The URL owns the view; back/forward use the previous URL, not hidden state.
  assert.deepEqual(read(discoverURL(original).split('?')[1]), original);
  const id = 'abc11111-1111-4111-8111-111111111111';
  assert.equal(read(discoverURL(read(`event_id=${id}`)).split('?')[1]).game, `event:${id}`);
});

test('Discover API forwards full-dataset filters, bounds and cancellation', async t => {
  const { api } = loadSource('lib/api.ts'); let request;
  t.mock.method(global, 'fetch', async (url, options) => { request = { url, options }; return { ok: true, json: async () => ({ props: [], total: 0 }) }; });
  const signal = new AbortController().signal;
  await api.getDiscover({ browse: true, offset: 24, limit: 24, sport: 'NHL', prop_type: 'shots_on_goal',
    search: 'McDavid', sportsbook: 'FanDuel', availability: 'last_known', game_date: '2026-10-21', sort: 'under_desc' }, signal);
  const params = new URL(request.url).searchParams;
  for (const [key,value] of Object.entries({ browse: 'true', offset: '24', limit: '24', search: 'McDavid',
    prop_type: 'shots_on_goal', sportsbook: 'FanDuel', availability: 'last_known', sort: 'under_desc' })) assert.equal(params.get(key), value);
  assert.equal(request.options.signal, signal);
});
