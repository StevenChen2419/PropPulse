const {test,expect}=require('@playwright/test');

// Opt in only against the guarded read-only API: no auth or mutation checks.
// Pass retained identities explicitly; this is never a synthetic/live-odds fixture.
test.skip(process.env.PROPPULSE_DEV_READONLY_BROWSER!=='1','Requires explicit read-only development API');
for(const width of [390,768,1440])test(`retained development data research ${width} (read-only)`,async({page})=>{
  const {PROPPULSE_DEV_PLAYER_ID:player,PROPPULSE_DEV_PROP_ID:prop,PROPPULSE_DEV_EVENT_ID:event}=process.env;
  expect(player&&prop&&event).toBeTruthy();
  const blocked=[],errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.setViewportSize({width,height:950});
  await page.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(['http://127.0.0.1:3199','http://localhost:8000'].includes(url.origin)&&['GET','OPTIONS'].includes(route.request().method()))return route.continue();
    blocked.push(`${route.request().method()} ${url.origin}`);return route.abort();
  });
  const noOverflow=async()=>expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.goto('/discover');
  await expect(page.getByRole('heading',{name:'No matching props',exact:true})).toBeVisible();
  await expect(page.locator('main').getByRole('alert')).toHaveCount(0);
  await noOverflow();
  await page.goto(`/player/${player}?prop_id=${prop}&sportsbook=DraftKings&offer_line=0.5&side=over`);
  const panel=page.getByRole('region',{name:'Verified exact-line research'});
  await expect(panel.getByRole('heading',{name:'Exact-line research · hits'})).toBeVisible();
  await expect(panel.getByText(/Expired odds/).first()).toBeVisible();
  await panel.getByText('Compare sportsbooks',{exact:false}).click();
  await expect(panel.getByText('No current best price confirmed')).toBeVisible();
  await expect(panel.getByText(/Price unavailable/).first()).toBeVisible();
  await panel.getByRole('button',{name:'L5',exact:true}).click();
  await expect(panel.getByRole('table').getByRole('row')).toHaveCount(6);
  await panel.getByRole('button',{name:'L10',exact:true}).press('Enter');
  await expect(panel.getByRole('table').getByRole('row')).toHaveCount(11);
  await panel.getByLabel('Exact research direction').selectOption('under');
  await expect(panel.getByText(/under hits:/).first()).toBeVisible();
  await noOverflow();
  expect(await panel.locator('.recharts-yAxis text').evaluateAll(labels=>labels.length>0&&labels.every(label=>
    label.getBoundingClientRect().left>=label.closest('.recharts-wrapper').getBoundingClientRect().left))).toBe(true);
  await panel.screenshot({path:test.info().outputPath(`development-research-${width}.png`)});
  await page.reload();
  await expect(panel.getByLabel('Exact research direction')).toHaveValue('under');
  await panel.getByLabel('Exact research sportsbook line').selectOption(JSON.stringify(['BetMGM',0.5]));
  await expect(panel.getByText(/BetMGM · under 0.5/)).toBeVisible();
  await panel.getByRole('button',{name:'Save exact selection',exact:true}).click();
  await expect(page).toHaveURL(/\/login$/); // auth-required, no writes
  await page.goto(`/games/${event}`);
  await expect(page.getByText(/Odds unavailable for this game/)).toBeVisible();
  await expect(page.locator('main').getByRole('alert')).toHaveCount(0);
  await noOverflow();
  await page.screenshot({path:test.info().outputPath(`development-game-${width}.png`),fullPage:true});
  expect(blocked).toEqual([]);expect(errors).toEqual([]);
});
