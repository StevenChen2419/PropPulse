const { test, expect } = require('@playwright/test');

for (const width of [390, 1440]) test(`freshness and coverage across research views ${width} (invented)`, async ({ page }) => {
  await page.setViewportSize({ width, height: 950 });
  const playerId='abcdef11-1111-4111-8111-111111111111', propId='abcdef22-2222-4222-8222-222222222222', eventId='abcdef33-3333-4333-8333-333333333333';
  const blocked=[], errors=[]; let expired=false;
  page.on('pageerror', error => errors.push(error.message));
  const coverage={ state:'partial_current_season', completeness:'unknown', season_scope:'current',
    season:'2026', competition:'Regular Season', source:'wehoop_wnba_stats', last_game_date:'2026-07-22',
    source_observed_at:'2026-10-20T12:00:00Z', recorded_appearances:8, l5_samples:5, l10_samples:8,
    limitations:['Invented offline fixture. Source completeness is unknown.'] };
  const window=n=>({appearances:n,points:{average:12,valid_samples:n-1}});
  await page.route('**/*', async route => {
    const url=new URL(route.request().url());
    if(url.origin==='http://127.0.0.1:3199') return route.continue();
    if(!['http://localhost:8000','http://127.0.0.1:8199'].includes(url.origin)) { blocked.push(url.origin);return route.abort(); }
    const headers={'access-control-allow-origin':'http://127.0.0.1:3199','access-control-allow-credentials':'true','access-control-allow-headers':'Content-Type,X-CSRF-Token','access-control-allow-methods':'GET,OPTIONS'};
    if(url.pathname==='/auth/csrf') return route.fulfill({status:200,headers,contentType:'application/json',body:JSON.stringify({csrf_token:'offline-csrf-proof'})});
    if(route.request().method()==='OPTIONS') return route.fulfill({status:204,headers});
    const json=body=>route.fulfill({status:200,headers,contentType:'application/json',body:JSON.stringify(body)});
    const now=Date.now(), observed=new Date(now-(expired?7:2)*3600000).toISOString();
    const freshness={availability:expired?'expired':'last_known',actionable:!expired,source:expired?'unavailable':'last_known',
      provider_observed_at:observed,refreshed_at:observed,ingested_at:new Date(now).toISOString(),expires_at:new Date(Date.parse(observed)+21600000).toISOString()};
    const context={event_id:eventId,identity_source:'authoritative',sport:'WNBA',sport_key:'basketball_wnba',provider:'the_odds_api',
      provider_event_id:'invented-event',odds_event_id:'invented-event',home_team:'Fixture Home',away_team:'Fixture Away',
      game_key:eventId,game_time:new Date(now+86400000).toISOString(),scheduled_start_at:new Date(now+86400000).toISOString()};
    const player={id:playerId,name:'Invented freshness player',sport:'WNBA',team:'Fixture Home',team_abbr:'FIX'};
    const prop={...context,...freshness,id:propId,player,statistics_coverage:coverage,prop_type:'points',line:20.5,
      sportsbook:'FanDuel',over_odds:expired?null:-110,under_odds:expired?null:120,is_home:true,popularity_count:0,
      sportsbook_count:expired?0:1,sportsbook_offers:expired?[]:[{...freshness,sportsbook:'FanDuel',line:20.5,over_odds:-110,under_odds:120}]};
    const summary={status:'available',sport:'WNBA',season:'2026',competition:'Regular Season',source:coverage.source,
      recorded_appearances:8,latest_appearance:coverage.last_game_date,coverage_start:'2026-06-01',coverage_end:coverage.last_game_date,
      last_observed_at:coverage.source_observed_at,date_precision:'eastern_date',reference_date:'2026-10-20',
      l5:window(5),l10:window(8),metrics:[{key:'points',label:'Points'}],coverage,notes:['Invented offline fixture.']};
    if(url.pathname==='/users/me') return json({id:'viewer',username:'Fixture',fav_players:[],fav_sports:[],fav_prop_types:[]});
    if(url.pathname==='/users/me/saved') return json({saved:[prop]});
    if(url.pathname==='/users/me/slip') return json({slip:{id:'fixture-slip',items:[{id:'item',prop_id:propId,prop,side:'under',selection:{...freshness,sportsbook:'FanDuel',line:20.5,odds:expired?null:120}}]}});
    if(url.pathname==='/props/discover'||url.pathname==='/props/feed') return json({props:[prop],total:1,supported_sports:['WNBA'],refreshed_at:observed});
    if(url.pathname==='/props/todays-games') return json([{...context,...freshness,prop_count:1,has_eligible_props:!expired}]);
    if(url.pathname==='/props/ingestion-status') return json({availability:'last_known',current_prop_count:1});
    if(url.pathname==='/props/game') return json({...context,...freshness,props:[prop],total_props:1,sportsbook_count:1,has_eligible_props:!expired});
    if(url.pathname==='/players/search') return json({players:[{...player,...freshness,statistics_coverage:coverage,live_prop_count:1,next_game_time:context.game_time,top_prop:null}]});
    if(url.pathname===`/players/${playerId}`) return json({...player,props:[prop],fatigue:null});
    if(url.pathname===`/players/${playerId}/research`) return json({player_id:playerId,sport:'WNBA',selected_prop:prop,available_props:[prop],
      selection_available:!expired,season_summary:summary,history:null,trends:null,games:[],splits:null,line_movement:null});
    blocked.push(url.pathname);return route.abort();
  });
  for(const path of ['/discover','/players','/saved',`/games/${eventId}`,`/player/${playerId}`]) {
    await page.goto(path);
    await expect(page.locator('main').getByText(/Stats through Jul 22, 2026/).first()).toBeVisible();
    await expect(page.locator('main').getByText(/Last known odds/).first()).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
  await page.goto('/saved');
  const card=page.locator('.prop-card').first();
  await card.locator('summary').filter({hasText:'Stats through'}).click();
  await expect(card.getByText(/Source coverage uncertain/)).toBeVisible();
  await expect(card.getByText(/L5: 5 appearances/)).toBeVisible();
  const slip=page.getByRole('region',{name:'Research slip'});
  const tab=slip.getByRole('button',{name:'My Slip'});
  if(await tab.getAttribute('aria-expanded')==='true') await tab.click();
  await page.screenshot({path:test.info().outputPath(`coverage-card-${width}.png`),fullPage:true});
  if(await tab.getAttribute('aria-expanded')==='false') await tab.click();
  await expect(slip.getByText(/Under/).first()).toBeVisible();
  await expect(slip.getByText(/Last known odds/)).toBeVisible();
  await page.screenshot({path:test.info().outputPath(`coverage-${width}.png`),fullPage:true});
  expired=true;await page.reload();
  await expect(page.locator('main').getByText(/Expired odds/).first()).toBeVisible();
  if(await tab.getAttribute('aria-expanded')==='false') await tab.click();
  await expect(slip.getByText(/Under/).first()).toBeVisible();
  await expect(slip.getByText(/Expired odds/).first()).toBeVisible();
  await expect(slip.getByText(/A selected offer is unavailable/)).toBeVisible();
  expect(blocked).toEqual([]);expect(errors).toEqual([]);
});
