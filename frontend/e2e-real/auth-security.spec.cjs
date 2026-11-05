const { test, expect } = require('@playwright/test');
const { createHmac, randomUUID } = require('node:crypto');

const API = 'http://127.0.0.1:8199';
const PROP = '00000000-0000-0000-0000-000000002454'; // synthetic fixture UUID(int=9300)
const PASSWORD = 'Browser-Fixture-Password!935';
const FIXTURE_SECRET = 'security-browser-fixture-only-4f837ae1dc0926b5';

// All operations go through the actual app, real cookie jar, CORS and PostgreSQL.
// There are no Playwright route fulfillments or mocked application API responses.
async function call(page, path, method = 'GET', body, csrf = true) {
  return page.evaluate(async ({ api, path, method, body, csrf }) => {
    const headers = { 'Content-Type': 'application/json' };
    if (csrf && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const proof = await fetch(`${api}/auth/csrf`, { credentials: 'include', cache: 'no-store' });
      headers['X-CSRF-Token'] = (await proof.json()).csrf_token;
    }
    const response = await fetch(`${api}${path}`, {
      method, credentials: 'include', cache: 'no-store', headers,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    return { status: response.status, body: await response.json() };
  }, { api: API, path, method, body, csrf });
}

async function assertNoBrowserCredentials(page) {
  const exposed = await page.evaluate(() => ({
    cookies: document.cookie,
    local: { ...localStorage }, session: { ...sessionStorage },
  }));
  expect(exposed.cookies).not.toMatch(/proppulse_(?:session|csrf)=/);
  expect(exposed.local).not.toHaveProperty('token');
  expect(exposed.session).not.toHaveProperty('token');
  for (const value of Object.values({ ...exposed.local, ...exposed.session })) {
    expect(value).not.toMatch(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/);
  }
}

async function signOut(page, mobile) {
  if (mobile) await page.getByRole('button', { name: 'Open navigation', exact: true }).click();
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
}

function expiredToken(subject) {
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const payload = Buffer.from(JSON.stringify({ sub: subject, exp: Math.floor(Date.now() / 1000) - 60 })).toString('base64url');
  const signingInput = `${header}.${payload}`;
  return `${signingInput}.${createHmac('sha256', FIXTURE_SECRET).update(signingInput).digest('base64url')}`;
}

test('real cookie auth, CSRF, refresh, selection persistence and ownership', async ({ page, context, browser }, testInfo) => {
  const mobile = testInfo.project.name === 'mobile';
  const email = `security-${randomUUID()}@example.com`;
  await page.goto('/login');
  await page.evaluate(() => localStorage.setItem('token', 'legacy-browser-token-fixture'));
  await page.reload();
  await expect.poll(() => page.evaluate(() => localStorage.getItem('token'))).toBeNull();

  const registration = await call(page, '/auth/register', 'POST', { email, password: PASSWORD });
  expect(registration).toEqual({ status: 200, body: { ok: true } });
  const me = await call(page, '/users/me');
  expect(me.status).toBe(200);
  expect(me.body.email).toBe(email);
  const cookie = (await context.cookies(API)).find(item => item.name === 'proppulse_session');
  expect(cookie).toBeDefined();
  expect(cookie.httpOnly).toBe(true);
  expect(cookie.sameSite).toBe('Lax');
  await assertNoBrowserCredentials(page);

  // Cross-origin unsafe requests and missing proofs fail without any mutation.
  expect((await call(page, '/users/me/preferences', 'PUT', { fav_sports: ['NFL'] }, false)).status).toBe(403);
  const csrf = await call(page, '/auth/csrf');
  const crossOrigin = await context.request.put(`${API}/users/me/preferences`, {
    headers: { Origin: 'https://untrusted.example', 'X-CSRF-Token': csrf.body.csrf_token },
    data: { fav_sports: ['NFL'] },
  });
  expect(crossOrigin.status()).toBe(403);
  expect((await call(page, '/users/me')).body.fav_sports).toEqual([]);

  expect((await call(page, `/interactions/${PROP}`, 'POST', { action: 'save' })).status).toBe(200);
  const over = { sportsbook: 'FanDuel', line: 20.5, side: 'over' };
  const under = { ...over, side: 'under' };
  const saved = await call(page, `/users/me/saved/selections/${PROP}`, 'POST', over);
  expect(saved.status).toBe(200);
  const selectionId = saved.body.id;
  expect((await call(page, `/users/me/saved/selections/${selectionId}/slip`, 'POST')).status).toBe(200);
  expect((await call(page, `/users/me/slip/items/${PROP}`, 'PATCH', under)).status).toBe(200);
  const persisted = await call(page, '/users/me/saved');
  expect(persisted.body.saved.map(item => item.id)).toContain(PROP);
  expect(persisted.body.selections.find(item => item.id === selectionId).side).toBe('over');
  expect((await call(page, '/users/me/slip')).body.slip.items[0].side).toBe('under');
  await page.goto('/saved');
  await expect(page.getByText('Security Fixture Player').first()).toBeVisible();
  await page.reload();
  await expect(page.getByText('Security Fixture Player').first()).toBeVisible();
  await assertNoBrowserCredentials(page);

  // A second browser owns a separate real session and cannot change the first.
  const other = await browser.newContext({ baseURL: 'http://127.0.0.1:3199' });
  try {
    const second = await other.newPage();
    await second.goto('/login');
    expect((await call(second, '/auth/register', 'POST', {
      email: `security-${randomUUID()}@example.com`, password: PASSWORD,
    })).status).toBe(200);
    expect((await call(second, '/users/me/saved')).body).toEqual({ saved: [], selections: [] });
    expect((await call(second, '/users/me/slip')).body.slip).toBeNull();
    for (const [path, method, body] of [
      [`/users/me/saved/selections/${selectionId}`, 'PATCH', under],
      [`/users/me/saved/selections/${selectionId}`, 'DELETE'],
      [`/users/me/saved/selections/${selectionId}/slip`, 'POST'],
      [`/users/me/slip/items/${PROP}`, 'PATCH', over],
    ]) expect((await call(second, path, method, body)).status).toBe(404);
    expect((await call(page, '/users/me/saved')).body.selections[0].id).toBe(selectionId);
    expect((await call(page, '/users/me/slip')).body.slip.items[0].side).toBe('under');
  } finally { await other.close(); }

  await signOut(page, mobile);
  expect((await call(page, '/users/me')).status).toBe(401);
  expect((await call(page, '/users/me/saved')).status).toBe(401);
  expect((await context.cookies(API)).some(item => item.name === 'proppulse_session')).toBe(false);
  await page.getByLabel('Email', { exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD);
  // Login navigates immediately; inspect status without a post-navigation body read.
  const loginResponse = page.waitForResponse(response => response.url() === `${API}/auth/login`
    && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  expect((await loginResponse).status()).toBe(200);
  await expect(page).toHaveURL('http://127.0.0.1:3199/');
  await page.goto('/saved');
  await expect(page.getByText('Security Fixture Player').first()).toBeVisible();
  expect((await call(page, '/users/me/slip')).body.slip.items[0].side).toBe('under');
  await assertNoBrowserCredentials(page);

  // Browser sends these real HttpOnly cookies; actual JWT verification rejects them.
  for (const value of ['invalid-session-fixture', expiredToken(me.body.id)]) {
    await context.addCookies([{ name: 'proppulse_session', value,
      domain: '127.0.0.1', path: '/', httpOnly: true, sameSite: 'Lax' }]);
    expect((await call(page, '/users/me')).status).toBe(401);
    await page.reload();
    await expect(page.getByText('Security Fixture Player')).toHaveCount(0);
    await assertNoBrowserCredentials(page);
  }
});
