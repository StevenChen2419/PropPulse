const { test, expect } = require('@playwright/test');

for (const width of [390, 1440]) test(`Discover SQL query contract and URL navigation ${width} (invented)`, async ({ page }) => {
  await page.setViewportSize({ width, height: 950 });
  const blocked=[], errors=[], requests=[];
  page.on('pageerror', error => errors.push(error.message));
  const uuid = index => `abc${String(index).padStart(5,'0')}-1111-4111-8111-111111111111`;
  const observed=new Date(Date.now()-7200000).toISOString();
  const start=new Date(Date.now()+86400000).toISOString();
  const gameDate=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(start));
  const freshness={availability:'last_known',actionable:true,source:'last_known',provider_observed_at:observed,
    refreshed_at:observed,expires_at:new Date(Date.parse(observed)+21600000).toISOString()};
  const context={event_id:uuid(200),identity_source:'authoritative',sport:'NHL',sport_key:'icehockey_nhl',
    provider:'the_odds_api',provider_event_id:'invented-game',odds_event_id:'invented-game',game_key:uuid(200),
    home_team:'Home Rivals',away_team:'Edmonton Oilers',game_time:start,scheduled_start_at:start};
  const props=Array.from({length:70},(_,index)=>({...freshness,...context,id:uuid(index+1),
    player:{id:uuid(index+1000),name:index===69?'Connor McDavid':`Invented Player ${String(index).padStart(3,'0')}`,
      team:'Edmonton Oilers',team_abbr:'EDM',sport:'NHL'},
    prop_type:'shots_on_goal',line:2.5,sportsbook:'FanDuel',over_odds:-110,under_odds:120,
    sportsbook_count:1,popularity_count:0,is_home:false,
    sportsbook_offers:[{...freshness,sportsbook:'FanDuel',line:2.5,over_odds:-110,under_odds:120}],
    statistics_coverage:{state:'partial_current_season',completeness:'unknown',season_scope:'current',
      season:'2026-27',competition:'Regular Season',source:'nhl_web',last_game_date:'2026-10-17',
      source_observed_at:'2026-10-18T12:00:00Z',recorded_appearances:8,l5_samples:5,l10_samples:8,
      limitations:['Invented offline fixture; completeness unknown.']}}));
  const selected=props[69];
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url());
    if(url.origin==='http://127.0.0.1:3199') return route.continue();
    if(!['http://localhost:8000','http://127.0.0.1:8199'].includes(url.origin)) {blocked.push(url.origin);return route.abort();}
    const headers={'access-control-allow-origin':'http://127.0.0.1:3199','access-control-allow-credentials':'true','access-control-allow-headers':'Content-Type,X-CSRF-Token','access-control-allow-methods':'GET,OPTIONS'};
    if(url.pathname==='/auth/csrf') return route.fulfill({status:200,headers,contentType:'application/json',body:JSON.stringify({csrf_token:'offline-csrf-proof'})});
    if(route.request().method()==='OPTIONS') return route.fulfill({status:204,headers});
    const json=body=>route.fulfill({status:200,headers,contentType:'application/json',body:JSON.stringify(body)});
    if(url.pathname==='/users/me') return json({id:'invented-viewer',username:'Fixture',fav_players:[],fav_sports:[],fav_prop_types:[]});
    if(url.pathname==='/users/me/saved') return json({saved:[selected]});
    if(url.pathname==='/users/me/slip') return json({slip:{id:'invented-slip',items:[{id:'item',prop_id:selected.id,prop:selected,side:'under',selection:{...freshness,sportsbook:'FanDuel',line:2.5,odds:120}}]}});
    if(url.pathname==='/props/todays-games') return json([{...context,...freshness,prop_count:70}]);
    if(url.pathname==='/props/discover') {
      const p=url.searchParams;requests.push(Object.fromEntries(p));
      expect(p.get('browse')).toBe('true');expect(Number(p.get('limit'))).toBe(24);
      let matches=props.filter(row=>(!p.get('search')||`${row.player.name} ${row.player.team}`.toLowerCase().includes(p.get('search').toLowerCase()))
        &&(!p.get('sport')||p.get('sport')==='NHL')&&(!p.get('prop_type')||p.get('prop_type')===row.prop_type));
      if(p.get('sort')==='player') matches=matches.toSorted((a,b)=>a.player.name.localeCompare(b.player.name));
      const offset=Number(p.get('offset')||0),limit=Number(p.get('limit'));
      return json({props:matches.slice(offset,offset+limit),total:matches.length,limit,offset,
        has_more:offset+limit<matches.length,next_offset:offset+limit<matches.length?offset+limit:null,
        supported_sports:['NBA','WNBA','NHL','NFL','MLB'],filter_options:{sports:['NBA','WNBA','NHL','NFL','MLB'],markets:['shots_on_goal','points'],sportsbooks:['FanDuel','DraftKings']}});
    }
    blocked.push(url.pathname);return route.abort();
  });
  await page.goto('/discover');
  await expect(page.getByRole('status').filter({hasText:'70 matching props'})).toBeVisible();
  const first=await page.locator('main .prop-card a').filter({hasText:'Research'}).evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')));
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.getByRole('status').filter({hasText:'Showing 25–48'})).toBeVisible();
  const second=await page.locator('main .prop-card a').filter({hasText:'Research'}).evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')));
  expect(new Set([...first,...second]).size).toBe(48);
  const search=page.getByRole('searchbox',{name:'Search Discover props'});
  await search.fill('McD');await search.fill('McDavid');
  await expect(page).toHaveURL(/search=McDavid/);
  await expect(page).not.toHaveURL(/page=/);
  await expect(page.locator('main .prop-card')).toHaveCount(1);
  expect(requests.filter(r=>r.search==='McD')).toHaveLength(0);
  await page.goBack();await expect(page).toHaveURL(/page=2/);
  await expect(search).toHaveValue('');
  await page.goForward();await expect(search).toHaveValue('McDavid');
  await expect(page.locator('main .prop-card')).toHaveCount(1);
  await page.getByRole('button',{name:'NHL',exact:true}).click();
  await page.getByRole('combobox',{name:'Prop market filter'}).selectOption('shots_on_goal');
  await page.getByRole('combobox',{name:'Sportsbook filter'}).selectOption('FanDuel');
  await page.getByRole('combobox',{name:'Odds availability filter'}).selectOption('last_known');
  await page.getByLabel('Game date (Eastern)',{exact:true}).fill(gameDate);
  await page.getByRole('combobox',{name:'Sort Discover'}).selectOption('under_desc');
  await expect(page.locator('main .prop-card')).toHaveCount(1);
  await expect(page.locator('main').getByText(/Last known odds/).first()).toBeVisible();
  await expect(page.locator('main').getByText(/Stats through Oct 17, 2026/)).toBeVisible();
  const card=page.locator('main .prop-card');
  await expect(card.getByTitle('Remove bookmark')).toHaveAttribute('aria-pressed','true');
  await expect(card.getByRole('button',{name:'Remove Under from Slip'})).toBeEnabled();
  await expect(card.getByRole('link',{name:/Research/})).toHaveAttribute('href',`/player/${selected.player.id}?prop_id=${selected.id}&sportsbook=FanDuel&offer_line=2.5&side=under`);
  const current=page.url();await page.reload();
  await expect(search).toHaveValue('McDavid');
  await expect(page.getByRole('combobox',{name:'Sportsbook filter'})).toHaveValue('FanDuel');
  await expect(page.getByRole('combobox',{name:'Sort Discover'})).toHaveValue('under_desc');
  await page.getByRole('combobox',{name:'Prop market filter'}).selectOption('points');
  await expect(page.getByText('No matching props',{exact:true})).toBeVisible();
  await page.goBack();await expect(page).toHaveURL(current);
  await expect(page.locator('main .prop-card')).toHaveCount(1);
  await page.goForward();await expect(page.getByText('No matching props',{exact:true})).toBeVisible();
  await page.goBack();await expect(page.locator('main .prop-card')).toHaveCount(1);
  const slipToggle=page.getByRole('region',{name:'Research slip'}).getByRole('button',{name:'My Slip'});
  if(await slipToggle.getAttribute('aria-expanded')==='true') await slipToggle.click();
  await page.evaluate(()=>window.scrollTo(0,0));
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:test.info().outputPath(`discover-${width}.png`),fullPage:true});
  await page.getByRole('button',{name:'Reset Filters',exact:true}).first().click();
  await expect(page).toHaveURL('http://127.0.0.1:3199/discover');
  await expect(search).toHaveValue('');
  await expect(page.getByRole('status').filter({hasText:'70 matching props'})).toBeVisible();
  // Changing a filter before the debounce must preserve a just-cleared search.
  await search.fill('McDavid');
  await expect(page).toHaveURL(/search=McDavid/);
  await search.fill('');
  await page.getByRole('combobox',{name:'Sort Discover'}).selectOption('player');
  await expect(page).toHaveURL(/sort=player/);
  await expect(page).not.toHaveURL(/search=/);
  await expect(search).toHaveValue('');
  await expect(page.getByRole('status').filter({hasText:'70 matching props'})).toBeVisible();
  await page.goto('/discover?sport=invalid&page=-1&sort=hit_rate');
  await expect(page.getByRole('status').filter({hasText:'70 matching props'})).toBeVisible();
  expect(blocked).toEqual([]);expect(errors).toEqual([]);
});
