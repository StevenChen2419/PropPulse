const {test,expect}=require('@playwright/test');

test('temporary failures keep auth, announce errors, and allow slip recovery (offline fixture)',async({page})=>{
  await page.setViewportSize({width:768,height:950});
  let discoverFails=true,slipFails=true,accountChecks=0;
  const blocked=[];
  await page.route('**/*', async route=>{
    const url=new URL(route.request().url());
    if(url.origin==='http://127.0.0.1:3199') return route.continue();
    if(!['http://localhost:8000','http://127.0.0.1:8199'].includes(url.origin)){blocked.push(url.origin);return route.abort();}
    const headers={'access-control-allow-origin':'http://127.0.0.1:3199','access-control-allow-credentials':'true','access-control-allow-headers':'Content-Type,X-CSRF-Token','access-control-allow-methods':'GET,OPTIONS'};
    if(url.pathname==='/auth/csrf') return route.fulfill({status:200,headers,contentType:'application/json',body:JSON.stringify({csrf_token:'offline-csrf-proof'})});
    if(route.request().method()==='OPTIONS') return route.fulfill({status:204,headers});
    const json=(body,status=200)=>route.fulfill({status,headers,contentType:'application/json',body:JSON.stringify(body)});
    if(url.pathname==='/users/me')return ++accountChecks === 1 ? json({id:'fixture-user',email:'fixture@example.invalid'}) : json({detail:'Temporary account outage'},503);
    if(url.pathname==='/users/me/saved')return json({saved:[],selections:[]});
    if(url.pathname==='/users/me/slip')return slipFails?json({detail:'Temporary outage'},503):json({slip:{items:[]}});
    if(url.pathname==='/props/todays-games')return json([]);
    if(url.pathname==='/props/discover')return discoverFails?json({detail:'Temporary outage'},503):json({props:[],total:0});
    blocked.push(url.pathname); return route.abort();
  });
  await page.goto('/discover');
  await expect(page.locator('main').getByRole('alert')).toBeVisible();
  await expect(page.locator('main').getByRole('status')).toHaveText('Search unavailable. Retry to load matching props.');
  expect(await page.evaluate(()=>localStorage.getItem('token'))).toBeNull();
  await expect(page.getByTitle('Signed in as fixture@example.invalid')).toBeVisible();
  const drawer=page.getByRole('region',{name:'Research slip'});
  await expect(drawer.getByRole('alert')).toContainText('Could not load your saved research slip');
  await expect(drawer.getByText('Your research slip is empty')).toHaveCount(0);
  slipFails=false;
  await drawer.getByRole('button',{name:'Retry slip'}).click();
  await expect(drawer.getByText('Your research slip is empty')).toBeVisible();
  await drawer.getByRole('button',{name:'My Slip'}).press('Escape');
  await expect(drawer.getByRole('button',{name:'My Slip'})).toHaveAttribute('aria-expanded','false');
  discoverFails=false;
  await page.locator('main').getByRole('button',{name:'Try again'}).click();
  await expect(page.getByText('No matching props',{exact:true})).toBeVisible();
  await expect(page.locator('main').getByRole('alert')).toHaveCount(0);
  expect(blocked).toEqual([]);
});
