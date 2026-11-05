const { test, expect } = require('@playwright/test');

test('Workers dynamic routing, API origin, session hydration and CSRF requests (offline)', async ({ page }) => {
  const requests = [], unexpected = [], errors = [];
  let authenticated = false;
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url());
    if (url.origin === 'http://127.0.0.1:3199') return route.continue();
    if (url.origin !== 'https://api.example.com') { unexpected.push(url.origin); return route.abort(); }
    requests.push({ path: url.pathname, method: req.method(), csrf: req.headers()['x-csrf-token'] });
    const headers = { 'access-control-allow-origin': 'http://127.0.0.1:3199', 'access-control-allow-credentials': 'true',
      'access-control-allow-headers': 'Content-Type,X-CSRF-Token', 'access-control-allow-methods': 'GET,POST,OPTIONS' };
    if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
    let body = {}, status = 200;
    if (url.pathname === '/auth/csrf') body = { csrf_token: 'offline-assessment-proof' };
    else if (url.pathname === '/auth/login') { status = 401; body = { detail: 'Invented rejected login' }; }
    else if (url.pathname === '/users/me') { status = authenticated ? 200 : 401; body = authenticated ? { id: 'offline-viewer', username: 'Offline assessment', fav_sports: [], fav_players: [], fav_prop_types: [] } : { detail: 'Not authenticated' }; }
    else if (url.pathname === '/users/me/saved') body = { saved: [], selections: [] };
    else if (url.pathname === '/users/me/slip') body = { slip: null };
    else if (url.pathname.startsWith('/players/') || url.pathname === '/props/game') { status = 404; body = { detail: 'No fixture data' }; }
    else if (url.pathname === '/players/search') body = { players: [], total: 0 };
    else if (url.pathname === '/props/todays-games') body = [];
    else body = { props: [], total: 0, groups: [], sports: [], available_sports: [] };
    return route.fulfill({ status, headers, contentType: 'application/json', body: JSON.stringify(body) });
  });
  for (const path of ['/discover', '/players', '/player/11111111-1111-4111-8111-111111111111?prop_id=22222222-2222-4222-8222-222222222222',
    '/games/33333333-3333-4333-8333-333333333333', '/saved', '/profile', '/login']) {
    const response = await page.goto(path);
    expect(response.status()).toBe(200);
    await expect(page.locator('body')).toContainText('PropPulse');
  }
  await page.getByLabel(/email/i).fill('assessment@example.com');
  await page.getByLabel(/password/i).fill('DisposableAssessment!472');
  await page.getByRole('button', { name: /sign in|log in/i }).click();
  await expect(page.getByText('Invented rejected login')).toBeVisible();
  expect(requests.some(r => r.path === '/users/me')).toBe(true);
  expect(requests.some(r => r.path === '/auth/csrf')).toBe(true);
  expect(requests.find(r => r.path === '/auth/login' && r.method === 'POST').csrf).toBe('offline-assessment-proof');
  authenticated = true;
  await page.goto('/saved');
  await expect.poll(() => requests.filter(r => r.path === '/users/me/saved').length).toBeGreaterThan(0);
  await expect.poll(() => requests.filter(r => r.path === '/users/me/slip').length).toBeGreaterThan(0);
  await page.getByRole('link', { name: 'Players', exact: true }).first().click();
  await expect(page).toHaveURL(/\/players/);
  expect(unexpected).toEqual([]);
  expect(errors).toEqual([]);
});
