const { test, expect } = require('@playwright/test');
const { randomUUID } = require('node:crypto');

const APP = 'https://app.proppulse.test:3443';
const API = 'https://api.proppulse.test:3443';
const PASSWORD = 'Disposable-Https-Fixture!736';
const PROP = process.env.PRODUCTION_TEST_PROP_ID;
const PLAYER = process.env.PRODUCTION_TEST_PLAYER_ID;
const EXPIRED_PROP = process.env.PRODUCTION_TEST_EXPIRED_PROP_ID;
const EXPIRED_PLAYER = process.env.PRODUCTION_TEST_EXPIRED_PLAYER_ID || PLAYER;
const PLAYER_NAME = process.env.PRODUCTION_TEST_PLAYER_NAME || 'Security Fixture Player';
const BOOK = process.env.PRODUCTION_TEST_SPORTSBOOK || 'FanDuel';
const LINE = Number(process.env.PRODUCTION_TEST_LINE || '20.5');
const SESSION = '__Host-proppulse_session';
const CSRF = '__Host-proppulse_csrf';

// Actual Chromium cookie jar, HTTPS gateway, hardened app and disposable PostgreSQL.
// No application API is mocked and no credential or cookie value is logged.
async function call(page, path, method = 'GET', body, proof = true) {
  return page.evaluate(async ({ api, path, method, body, proof }) => {
    const headers = { 'Content-Type': 'application/json' };
    if (proof && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const response = await fetch(`${api}/auth/csrf`, { credentials: 'include', cache: 'no-store' });
      headers['X-CSRF-Token'] = (await response.json()).csrf_token;
    }
    const response = await fetch(`${api}${path}`, {
      method, credentials: 'include', cache: 'no-store', headers,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const text = await response.text();
    return { status: response.status, body: text ? JSON.parse(text) : null };
  }, { api: API, path, method, body, proof });
}

async function gatewayRequest(context, url, options) {
  try { return await context.request.fetch(url, options); }
  catch { throw new Error('HTTPS gateway probe failed; request details suppressed to protect test credentials.'); }
}

async function noBrowserCredentials(page) {
  const result = await page.evaluate(() => ({ cookie: document.cookie,
    values: [...Object.entries(localStorage), ...Object.entries(sessionStorage)] }));
  expect(result.cookie.includes('proppulse_session=')).toBe(false);
  expect(result.cookie.includes('proppulse_csrf=')).toBe(false);
  expect(result.values.some(([key]) => /^(?:token|access_token|jwt)$/i.test(key))).toBe(false);
  expect(result.values.some(([, value]) => /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/.test(value))).toBe(false);
}

async function assertCookieAttributes(context) {
  const cookies = await context.cookies(API);
  for (const name of [SESSION, CSRF]) {
    const cookie = cookies.find(cookie => cookie.name === name);
    expect(Boolean(cookie), `${name} must exist`).toBe(true);
    expect(cookie.secure).toBe(true);
    expect(cookie.httpOnly).toBe(true);
    expect(cookie.sameSite).toBe('Lax');
    expect(cookie.path).toBe('/');
    expect(cookie.domain).toBe('api.proppulse.test');
    expect(cookie.expires).toBeGreaterThan(Date.now() / 1000);
  }
  expect((await context.cookies(APP)).some(cookie => [SESSION, CSRF].includes(cookie.name))).toBe(false);
}

async function logout(page, mobile) {
  if (mobile) await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page).toHaveURL(`${APP}/login`);
}

test('production HTTPS cookie auth, CSRF, CORS, research and ownership', async ({ page, context, browser }, testInfo) => {
  expect(Boolean(PROP && PLAYER && EXPIRED_PROP), 'explicit disposable fixture IDs are required').toBe(true);
  const mobile = testInfo.project.name === 'mobile';
  const email = `https-${randomUUID()}@example.com`;
  const navigation = await page.goto('/login');
  expect(navigation.status()).toBe(200);
  await noBrowserCredentials(page);
  const registration = await call(page, '/auth/register', 'POST', { email, password: PASSWORD });
  expect(registration.status).toBe(200);
  expect(Object.keys(registration.body)).toEqual(['ok']);
  expect(registration.body.ok).toBe(true);
  expect((await call(page, '/users/me')).body.email).toBe(email);
  await assertCookieAttributes(context);
  await noBrowserCredentials(page);

  // Missing proof is refused before the protected write occurs.
  expect((await call(page, '/users/me/preferences', 'PUT', { fav_sports: ['NFL'] }, false)).status).toBe(403);
  const proof = (await call(page, '/auth/csrf')).body.csrf_token;
  // APIRequestContext does not inherit Chromium DNS rules. Address the local
  // HTTPS gateway by IP and select the API virtual host explicitly. Cookie
  // values stay inside the test process and are never included in assertions.
  const cookieHeader = (await context.cookies(API)).map(cookie => `${cookie.name}=${cookie.value}`).join('; ');
  const gateway = 'https://127.0.0.1:3443';
  const host = 'api.proppulse.test:3443';
  for (const provenance of [
    { Origin: 'https://untrusted.example', Referer: `${APP}/` },
    { Referer: 'https://untrusted.example/' },
    {},
  ]) {
    const rejected = await gatewayRequest(context, `${gateway}/users/me/preferences`, {
      method: 'PUT',
      headers: { Host: host, Cookie: cookieHeader, 'X-CSRF-Token': proof, ...provenance },
      data: { fav_sports: ['NFL'] },
    });
    expect(rejected.status()).toBe(403);
  }
  expect((await call(page, '/users/me')).body.fav_sports).toEqual([]);
  const preflight = await gatewayRequest(context, `${gateway}/users/me/preferences`, {
    method: 'OPTIONS', headers: { Host: host, Origin: APP,
      'Access-Control-Request-Method': 'PUT',
      'Access-Control-Request-Headers': 'content-type,x-csrf-token' },
  });
  expect(preflight.status()).toBe(200);
  expect(preflight.headers()['access-control-allow-origin']).toBe(APP);
  expect(preflight.headers()['access-control-allow-credentials']).toBe('true');
  const untrusted = await gatewayRequest(context, `${gateway}/users/me/preferences`, {
    method: 'OPTIONS', headers: { Host: host, Origin: 'https://untrusted.example',
      'Access-Control-Request-Method': 'PUT' },
  });
  expect(untrusted.status()).toBe(400);
  expect(untrusted.headers()['access-control-allow-origin']).toBeUndefined();

  const over = { sportsbook: BOOK, line: LINE, side: 'over' };
  const under = { ...over, side: 'under' };
  expect((await call(page, `/interactions/${PROP}`, 'POST', { action: 'save' })).status).toBe(200);
  const saved = await call(page, `/users/me/saved/selections/${PROP}`, 'POST', over);
  expect(saved.status).toBe(200);
  const savedId = saved.body.id;
  expect((await call(page, `/users/me/saved/selections/${savedId}`, 'PATCH', under)).status).toBe(200);
  expect((await call(page, `/users/me/saved/selections/${savedId}/slip`, 'POST')).status).toBe(200);
  expect((await call(page, `/users/me/slip/items/${PROP}`, 'PATCH', over)).status).toBe(200);
  expect((await call(page, '/users/me/slip')).body.slip.items[0].side).toBe('over');
  await page.goto('/saved');
  await expect(page.locator('main').getByText(PLAYER_NAME).first()).toBeVisible();
  await page.reload();
  await expect(page.locator('main').getByText(PLAYER_NAME).first()).toBeVisible();
  await noBrowserCredentials(page);

  // Exercise the actual frontend write path and its cached session-bound CSRF
  // proof, in addition to the endpoint-level ownership probes below.
  const drawer = page.getByRole('region', { name: 'Research slip' });
  const toggle = drawer.getByRole('button', { name: 'My Slip' });
  if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click();
  await drawer.getByRole('button', { name: 'Edit selection', exact: true }).click();
  await drawer.getByLabel('Edit slip direction').selectOption('under');
  await drawer.getByText('Compare sportsbooks', { exact: false }).click();
  await drawer.getByRole('region', { name: `under ${LINE} sportsbook comparison` })
    .getByRole('button', { name: 'Selected', exact: true }).click();
  await drawer.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(drawer.getByRole('button', { name: 'Edit selection', exact: true })).toBeVisible();
  expect((await call(page, '/users/me/slip')).body.slip.items[0].side).toBe('under');
  await page.reload();
  await expect(page.locator('main').getByText(PLAYER_NAME).first()).toBeVisible();

  const secondContext = await browser.newContext({ baseURL: APP, ignoreHTTPSErrors: true });
  try {
    const other = await secondContext.newPage();
    await other.goto('/login');
    expect((await call(other, '/auth/register', 'POST', {
      email: `https-other-${randomUUID()}@example.com`, password: PASSWORD,
    })).status).toBe(200);
    expect((await call(other, '/users/me/saved')).body).toEqual({ saved: [], selections: [] });
    for (const [path, method, body] of [
      [`/users/me/saved/selections/${savedId}`, 'PATCH', over],
      [`/users/me/saved/selections/${savedId}`, 'DELETE'],
      [`/users/me/saved/selections/${savedId}/slip`, 'POST'],
      [`/users/me/slip/items/${PROP}`, 'PATCH', under],
    ]) expect((await call(other, path, method, body)).status).toBe(404);
  } finally { await secondContext.close(); }

  await logout(page, mobile);
  expect((await call(page, '/users/me')).status).toBe(401);
  expect((await context.cookies(API)).some(cookie => cookie.name === SESSION)).toBe(false);
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  const response = page.waitForResponse(response => response.url() === `${API}/auth/login` && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page).toHaveURL(`${APP}/`);
  await assertCookieAttributes(context);
  await page.goto('/saved');
  await expect(page.locator('main').getByText(PLAYER_NAME).first()).toBeVisible();
  expect((await call(page, '/users/me/saved')).body.selections.find(row => row.id === savedId).side).toBe('under');
  expect((await call(page, '/users/me/slip')).body.slip.items[0].side).toBe('under');

  await page.goto('/discover');
  await expect(page.getByRole('heading', { name: 'Discover', exact: true })).toBeVisible();
  await expect(page.locator('main .prop-card').filter({ hasText: PLAYER_NAME }).first()).toBeVisible();
  const discover = await call(page, '/props/discover?browse=true&limit=50');
  expect(discover.status).toBe(200);
  expect(discover.body.props.some(prop => prop.id === PROP)).toBe(true);
  expect(discover.body.props.some(prop => prop.id === EXPIRED_PROP)).toBe(false);
  await page.goto(`/player/${PLAYER}?prop_id=${PROP}`);
  await expect(page.locator('main').getByText(PLAYER_NAME).first()).toBeVisible();
  const expired = await call(page, `/players/${EXPIRED_PLAYER}/research?prop_id=${EXPIRED_PROP}`);
  expect(expired.status).toBe(200);
  expect(expired.body.selected_prop.actionable).toBe(false);
  await page.goto(`/player/${EXPIRED_PLAYER}?prop_id=${EXPIRED_PROP}`);
  await expect(page.locator('main').getByText(/Expired odds|Price unavailable|Odds unavailable/).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await noBrowserCredentials(page);

  await page.goto('/saved');
  await expect(page.getByRole('region', { name: 'Exact saved selections' })).toBeVisible();
  if (await toggle.getAttribute('aria-expanded') === 'true') await toggle.click();
  await page.getByRole('region', { name: 'Exact saved selections' })
    .getByRole('button', { name: 'Unsave selection', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Exact saved selections' })).toHaveCount(0);
  expect((await call(page, `/interactions/${PROP}/save`, 'DELETE')).status).toBe(200);
  expect((await call(page, `/interactions/slip/${PROP}`, 'DELETE')).status).toBe(200);
  expect((await call(page, '/users/me/saved')).body).toEqual({ saved: [], selections: [] });
  // Expire the actual Secure host-only browser cookie. The server must receive
  // no authenticated session, and protected UI must stop displaying the library.
  // Server-side signed JWT expiry is covered separately by the backend/Stage 2.
  const session = (await context.cookies(API)).find(cookie => cookie.name === SESSION);
  await context.addCookies([{ ...session, expires: Math.floor(Date.now() / 1000) - 60 }]);
  expect((await call(page, '/users/me')).status).toBe(401);
  await page.reload();
  await expect(page).toHaveURL(`${APP}/login`);
  await noBrowserCredentials(page);
});
