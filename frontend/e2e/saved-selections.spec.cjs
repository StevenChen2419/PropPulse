const { test, expect } = require('@playwright/test');

for (const width of [390, 768, 1440]) test(`exact library and in-place slip editing ${width} (offline fixture)`, async ({ page }) => {
  await page.setViewportSize({width,height:950});
  const errors=[],blocked=[];
  page.on('pageerror', e=>errors.push(e.message));
  const propId='abcdef22-2222-4222-8222-222222222222';
  const playerId='abcdef11-1111-4111-8111-111111111111';
  const start=new Date(Date.now()+86400000).toISOString();
  const observed=new Date(Date.now()-60000).toISOString();
  const freshness={actionable:true,availability:'available',provider_observed_at:observed,expires_at:new Date(Date.now()+21540000).toISOString()};
  const fd={...freshness,sportsbook:'FanDuel',line:2.5,odds:-110};
  const dk={...freshness,sportsbook:'DraftKings',line:3.5,odds:120};
  const unavailable={...fd,sportsbook:'BetMGM',odds:null,actionable:false,availability:'market_unavailable'};
  const prop={...freshness,id:propId,player:{id:playerId,name:'Invented Selection Player',sport:'NHL',team:'Fixture Team',team_abbr:'FIX'},
    event_id:'abcdef33-3333-4333-8333-333333333333',game_time:start,prop_type:'shots_on_goal',line:2.5,sportsbook:'FanDuel',over_odds:-110,under_odds:-110,
    sportsbook_count:2,popularity_count:0,sportsbook_offers:[{...freshness,sportsbook:'FanDuel',line:2.5,over_odds:-110,under_odds:-110}],
    comparison:{prop_id:propId,player_id:playerId,event_id:'fixture-event',market:'shots_on_goal',groups:[
      {side:'over',line:2.5,offers:[fd],best:fd},
      {side:'under',line:2.5,offers:[{...fd,odds:110},unavailable],best:{...fd,odds:110}},
      {side:'under',line:3.5,offers:[dk],best:dk}]}};
  let saved=[],slip={id:'stable-item',prop_id:propId,prop,side:'over',selection:{...fd,original_odds:-120,original_observed_at:observed,price_change:'improved'}};
  let failEdit=true,expired=false,editCount=0,failLoad=false;
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url()), method=route.request().method();
    if(url.origin==='http://127.0.0.1:3199') return route.continue();
    if(!['http://localhost:8000','http://127.0.0.1:8199'].includes(url.origin)){blocked.push(url.origin);return route.abort();}
    const headers={'access-control-allow-origin':'http://127.0.0.1:3199','access-control-allow-credentials':'true','access-control-allow-headers':'Content-Type,X-CSRF-Token','access-control-allow-methods':'GET,POST,PATCH,DELETE,OPTIONS'};
    if(method==='OPTIONS') return route.fulfill({status:204,headers});
    const json=(body,status=200)=>route.fulfill({status,headers,contentType:'application/json',body:JSON.stringify(body)});
    if(url.pathname==='/auth/csrf') return json({csrf_token:'offline-csrf-proof'});
    if(url.pathname==='/users/me') return json({id:'viewer',username:'Fixture',fav_sports:[],fav_players:[],fav_prop_types:[]});
    if(url.pathname==='/users/me/saved') return json({saved:[prop],selections:saved});
    if(url.pathname==='/users/me/slip') {
      if(failLoad) { failLoad=false; return json({detail:'Stored offers temporarily unavailable. Retry loading.'},503); }
      return json({slip:{id:'slip',status:'open',items:[expired?{...slip,selection:{...slip.selection,odds:null,actionable:false,availability:'expired',price_change:null}}:slip]}});
    }
    if(url.pathname===`/users/me/saved/selections/${propId}` && method==='POST'){
      const body=route.request().postDataJSON();
      expect(body).toEqual({sportsbook:'FanDuel',line:2.5,side:'over'});
      saved=[{id:'exact',prop_id:propId,prop,side:body.side,selection:{...fd,original_odds:-110,original_observed_at:observed,price_change:'unchanged'}}];
      return json({id:'exact'});
    }
    if(url.pathname==='/users/me/saved/selections/exact' && method==='DELETE'){saved=[];return json({ok:true});}
    if(url.pathname===`/users/me/slip/items/${propId}` && method==='PATCH'){
      editCount++;
      if(failEdit){failEdit=false;return json({detail:'Offer changed. Original selection kept.'},409);}
      const body=route.request().postDataJSON();
      expect(body).toEqual({sportsbook:'DraftKings',line:3.5,side:'under'});
      slip={...slip,side:body.side,selection:{...dk,original_odds:120,original_observed_at:observed,price_change:'unchanged'}};
      return json({id:slip.id,selection:slip.selection});
    }
    if(url.pathname==='/users/me/saved/selections/exact/slip') return json({detail:'This prop already has a different slip selection. Edit it in your slip.'},409);
    blocked.push(`${method} ${url.pathname}`); return route.abort();
  });
  await page.goto('/saved');
  await expect(page.getByRole('heading',{name:'Generic bookmarks',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Save exact selection',exact:true}).click();
  await expect(page.getByRole('button',{name:'Unsave exact selection',exact:true})).toBeVisible();
  const library=page.getByRole('region',{name:'Exact saved selections'});
  await expect(library).toBeVisible();
  await expect(library.getByText('Originally selected: -110',{exact:true})).toBeVisible();
  await expect(library.getByRole('link',{name:'Research exact line'})).toHaveAttribute('href',`/player/${playerId}?prop_id=${propId}&sportsbook=FanDuel&offer_line=2.5&side=over`);
  await page.getByLabel('Search saved props').fill('missing');
  await expect(page.getByText('No saved items match these filters.')).toBeVisible();
  await page.getByLabel('Search saved props').fill('shots');
  await page.getByLabel('Saved sport').selectOption('NHL');
  await page.getByLabel('Saved type').selectOption('exact');
  await expect(page.getByRole('region',{name:'Generic bookmarks'})).toHaveCount(0);
  await expect(library).toBeVisible();
  const drawer=page.getByRole('region',{name:'Research slip'});
  const toggle=drawer.getByRole('button',{name:'My Slip'});
  if(await toggle.getAttribute('aria-expanded')==='false') await toggle.click();
  await drawer.getByRole('button',{name:'Edit selection',exact:true}).click();
  await expect(drawer.getByLabel('Edit slip direction')).toBeFocused();
  await drawer.getByLabel('Edit slip direction').selectOption('under');
  await drawer.getByText('Compare sportsbooks', {exact:false}).click();
  await drawer.getByRole('region',{name:'under 2.5 sportsbook comparison'}).getByRole('button',{name:'Use line for research',exact:true}).click();
  await expect(drawer.getByRole('alert')).toHaveText('This alternative is unavailable. Original selection kept.');
  await expect(drawer.getByRole('button',{name:'Save changes'})).toBeDisabled();
  await drawer.getByRole('region',{name:'under 3.5 sportsbook comparison'}).getByRole('button',{name:'Use line for research'}).click();
  await drawer.getByRole('button',{name:'Save changes'}).click();
  await expect(drawer.getByRole('alert')).toHaveText('Offer changed. Original selection kept.');
  await expect(drawer.getByText('Originally selected: -120',{exact:true})).toBeVisible();
  await drawer.getByRole('button',{name:'Save changes'}).click();
  await expect(drawer.getByRole('button',{name:'Edit selection',exact:true})).toBeVisible();
  await expect(drawer.getByText('Under 3.5',{exact:true})).toBeVisible();
  await expect(drawer.getByText('Originally selected: +120',{exact:true})).toBeVisible();
  expect(editCount).toBe(2);expect(slip.id).toBe('stable-item');
  await toggle.click();
  await page.reload();
  if(await toggle.getAttribute('aria-expanded')==='false') await toggle.click();
  await expect(drawer.getByText('Under 3.5',{exact:true})).toBeVisible();
  expired=true;
  await page.reload();
  if(await toggle.getAttribute('aria-expanded')==='false') await toggle.click();
  await expect(drawer.getByText('Current price unavailable.',{exact:true})).toBeVisible();
  await expect(drawer.getByText('Under 3.5',{exact:true})).toBeVisible();
  failLoad=true;
  await drawer.getByRole('button',{name:'Edit selection',exact:true}).click();
  await expect(drawer.getByRole('alert')).toContainText('Stored offers temporarily unavailable');
  await expect(drawer.getByText('Compare sportsbooks',{exact:false})).toHaveCount(0);
  await drawer.getByRole('button',{name:'Retry loading offers'}).click();
  await expect(drawer.getByRole('alert')).toHaveCount(0);
  await drawer.getByRole('button',{name:'Cancel',exact:true}).click();
  await expect(drawer.getByRole('button',{name:'Edit selection',exact:true})).toBeFocused();
  await toggle.click();
  await expect(library).toBeVisible();
  await library.getByRole('button',{name:'Add to research slip'}).click();
  await expect(page.locator('main').getByRole('alert')).toHaveText('This prop already has a different slip selection. Edit it in your slip.');
  await library.getByRole('button',{name:'Unsave selection'}).click();
  await expect(library).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  expect(blocked).toEqual([]);expect(errors).toEqual([]);
});
