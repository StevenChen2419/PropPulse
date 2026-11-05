const { test, expect } = require('@playwright/test');
const fixtures = require('../tests/fixtures/exact-line-research.json');

for (const width of [390,768,1440]) test(`verified exact-line multi-sport research ${width} (invented)`,async({page})=>{
  await page.setViewportSize({width,height:950});
  let active=fixtures.find(f=>f.sport==='WNBA'&&f.exact.side==='under');
  const id='abc12345-1111-4111-8111-111111111111',event='abc54321-1111-4111-8111-111111111111';
  const errors=[],blocked=[],calls=[];
  page.on('pageerror',e=>errors.push(e.message));
  const freshness=()=>({actionable:true,availability:'available',source:'live',provider_observed_at:new Date().toISOString(),
    expires_at:new Date(Date.now()+21600000).toISOString()});
  function comparison() {
    const a=active.exact;
    const row=(book,line,odds,stale=false)=>({...freshness(),sportsbook:book,line,odds,
      provider_bookmaker_key:book.toLowerCase(),provider_title:book,
      ...(stale?{actionable:false,availability:'last_known',provider_observed_at:new Date(Date.now()-31*60000).toISOString()}: {})});
    const fd=row('FanDuel',2,-110),mgm=row('BetMGM',2,120),dk=row('DraftKings',2.5,-120),old=row('Bovada',2.5,300,true);
    return {prop_id:id,player_id:a.player_id,event_id:event,market:a.market,groups:[
      {line:2,side:'under',offers:[fd,mgm],best:mgm,advantage_per_100:29.0909},
      {line:2.5,side:'under',offers:[dk,old],best:dk,advantage_per_100:null},
      {line:2,side:'over',offers:[fd,mgm],best:mgm,advantage_per_100:29.0909},
      {line:2.5,side:'over',offers:[dk,old],best:dk,advantage_per_100:null},
    ]};
  }
  function prop(fresh=true){
    const a=active.exact, start=new Date(Date.now()+86400000).toISOString();
    return {...(fresh?freshness():{...a.selection}),id,player:{id:a.player_id,name:`Invented ${active.sport} ${active.role??'player'}`,sport:active.sport,team:'Fixture Home',team_abbr:'FIX'},
      prop_type:a.market,line:2,sportsbook:'FanDuel',over_odds:fresh?-110:null,under_odds:fresh?120:null,
      event_id:event,odds_event_id:'invented-event',identity_source:'authoritative',home_team:'Fixture Home',away_team:'Fixture Away',
      game_key:event,sport:active.sport,game_time:start,scheduled_start_at:start,sportsbook_count:fresh?2:0,
      comparison:comparison(),statistics_coverage:a.coverage,sportsbook_offers:fresh?[{...freshness(),sportsbook:'FanDuel',line:2,over_odds:-110,under_odds:120},
        {...freshness(),sportsbook:'DraftKings',line:2.5,over_odds:110,under_odds:-120}]:[]};
  }
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url()),p=url.searchParams;
    if(url.origin==='http://127.0.0.1:3199')return route.continue();
    if(!['http://localhost:8000','http://127.0.0.1:8199'].includes(url.origin)){blocked.push(url.origin);return route.abort();}
    const headers={'access-control-allow-origin':'http://127.0.0.1:3199','access-control-allow-credentials':'true','access-control-allow-headers':'Content-Type,X-CSRF-Token','access-control-allow-methods':'GET,OPTIONS'};
    if(url.pathname==='/auth/csrf') return route.fulfill({status:200,headers,contentType:'application/json',body:JSON.stringify({csrf_token:'offline-csrf-proof'})});
    if(route.request().method()==='OPTIONS')return route.fulfill({status:204,headers});
    const json=body=>route.fulfill({status:200,headers,contentType:'application/json',body:JSON.stringify(body)});
    if(url.pathname==='/users/me')return json({id:'invented-viewer',username:'Fixture',fav_players:[],fav_sports:[],fav_prop_types:[]});
    if(url.pathname==='/users/me/saved')return json({saved:[prop()]});
    if(url.pathname==='/users/me/slip')return json({slip:{id:'fixture-slip',items:[{id:'item',prop_id:id,side:'under',prop:prop(),selection:{...freshness(),sportsbook:'DraftKings',line:2.5,odds:-120}}]}});
    if(url.pathname==='/props/todays-games')return json([]);
    if(url.pathname==='/props/discover')return json({props:[prop()],total:1,supported_sports:['NBA','WNBA','NHL','NFL','MLB']});
    if(url.pathname.endsWith('/research')){
      calls.push(Object.fromEntries(p));
      let exact=structuredClone(active.exact);
      if(active.sport==='WNBA')exact=structuredClone(fixtures.find(f=>f.sport==='WNBA'&&f.exact.line===Number(p.get('offer_line')||2)).exact);
      if(p.get('side')&&p.get('side')!==exact.side){
        exact.side=p.get('side');
        for(const window of [exact.l5,exact.l10,exact.season_window,...exact.opponents.flatMap(o=>[o.l5,o.l10,o.season_window])]){
          [window.hits,window.losses]=[window.losses,window.hits];
          window.raw_hit_rate=window.valid_samples?window.hits/window.valid_samples:null;
          window.settled_hit_rate=window.settled_decisions?window.hits/window.settled_decisions:null;
        }
      }
      exact.comparison=comparison();
      exact.movement={status:'unavailable',reason:'Stored snapshots record ingestion, not verified sportsbook observations. Price and line movement unavailable.'};
      exact.selection.side=exact.side;
      if(p.get('season')&&p.get('season')!==active.exact.season){
        exact.status='no_recorded_games';exact.games=[];exact.opponents=[];exact.season=p.get('season');
        for(const key of ['l5','l10','season_window'])exact[key]={appearances:0,valid_samples:0,missing_samples:0,over_hits:0,under_hits:0,pushes:0,hits:0,losses:0,raw_hit_rate:null,settled_decisions:0,settled_hit_rate:null};
      }
      return json({player_id:exact.player_id,sport:active.sport,selected_prop:prop(false),available_props:[],exact_line:exact,
        selection_available:false,trends:null,games:[],history:null,splits:null,line_movement:null,season_summary:null});
    }
    if(url.pathname.startsWith('/players/'))return json({...prop().player,props:[],fatigue:null});
    blocked.push(url.pathname);return route.abort();
  });
  await page.goto('/discover');
  const link=page.locator('main .prop-card').getByRole('link',{name:/Research/});
  await expect(link).toHaveAttribute('href',`/player/${active.exact.player_id}?prop_id=${id}&sportsbook=DraftKings&offer_line=2.5&side=under`);
  const card=page.locator('main .prop-card');
  await card.getByText('Compare sportsbooks', {exact:false}).click();
  const same=card.getByRole('region',{name:'under 2.5 sportsbook comparison',exact:true});
  await expect(same).toContainText('Best live price: DraftKings -120');
  await expect(same).toContainText('Bovada · +300');
  await expect(same).toContainText('Last known odds');
  await expect(card.getByRole('region',{name:'under 2 sportsbook comparison',exact:true})).toContainText('Alternative line');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await link.click();
  const panel=page.getByRole('region',{name:'Verified exact-line research'});
  await expect(panel).toBeVisible();
  await expect(panel.getByText(/DraftKings · under 2.5/)).toBeVisible();
  await expect(panel.getByText(/under hits: 2\/3 valid outcomes/).first()).toBeVisible();
  await expect(panel.getByText(/Expired odds/)).toBeVisible();
  await expect(panel.locator('.recharts-reference-line')).toHaveCount(1);
  await expect(panel.getByRole('table',{name:'Exact-line recorded games'})).toContainText('Unavailable · missing');
  await expect(panel.getByRole('columnheader',{name:'Verified opponent'})).toBeVisible();
  await panel.getByRole('button',{name:'L5',exact:true}).click();
  await expect(panel.getByRole('button',{name:'L5',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(panel.getByRole('status')).toContainText('4 recorded appearances · 3 valid values');
  await panel.getByRole('button',{name:'L10',exact:true}).click();
  await expect(panel.getByRole('figure')).toHaveAccessibleName(/recorded results at line 2.5/);
  await panel.getByText('Compare sportsbooks', {exact:false}).click();
  const alternative=panel.getByRole('region',{name:'under 2 sportsbook comparison',exact:true});
  await expect(alternative).toContainText('Best live price: BetMGM +120');
  await alternative.getByRole('button',{name:'Use line for research'}).first().click();
  await expect(panel.getByRole('combobox',{name:'Exact research sportsbook line'})).toHaveValue(JSON.stringify(['FanDuel',2]));
  await expect(panel.getByText(/Stored snapshots record ingestion/)).toBeVisible();
  await expect(panel.getByText(/1 pushes/).first()).toBeVisible();
  await panel.getByRole('combobox',{name:'Exact research direction'}).selectOption('over');
  await expect(panel.getByText(/over hits: 1\/3 valid outcomes/).first()).toBeVisible();
  const opponent=active.exact.opponents[0].opponent_id;
  await panel.getByRole('combobox',{name:'Verified opponent'}).selectOption(opponent);
  await expect(panel.getByText(/Recorded values:/)).toBeVisible();
  await page.getByRole('combobox',{name:'WNBA statistics season'}).selectOption('2026');
  await expect(panel.getByText(/No eligible completed games/)).toBeVisible();
  await page.goBack();await expect(panel.getByText(/over hits: 1\/3 valid outcomes/).first()).toBeVisible();
  const slip=page.getByRole('region',{name:'Research slip'}),toggle=slip.getByRole('button',{name:'My Slip'});
  if(await toggle.getAttribute('aria-expanded')==='false')await toggle.click();
  await expect(slip.getByText(/Under 2.5/).first()).toBeVisible();
  await expect(slip.getByText('DraftKings',{exact:true})).toBeVisible();
  if(await toggle.getAttribute('aria-expanded')==='true')await toggle.click();
  for(const fixture of fixtures.filter(f=>f.exact.side==='over')){
    active=fixture;
    await page.goto(`/player/${active.exact.player_id}?prop_id=${id}&season=${active.exact.season}`);
    await expect(panel.getByText(/over hits: 1\/3 valid outcomes/).first()).toBeVisible();
    await expect(panel.locator('.recharts-bar-rectangle path')).toHaveCount(3); // missing observations are gaps
    // Wait for chart animation, then verify the whole-line push meets the
    // reference exactly and the Over bar extends above it.
    await expect.poll(async()=>{
      const push=await panel.locator('.recharts-bar-rectangle path').nth(1).boundingBox();
      const over=await panel.locator('.recharts-bar-rectangle path').nth(2).boundingBox();
      const line=await panel.locator('.recharts-reference-line line').boundingBox();
      return !!(push&&over&&line&&Math.abs(push.y-line.y)<1&&over.y<line.y);
    }).toBe(true);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  }
  await panel.getByText('Compare sportsbooks', {exact:false}).click();
  await expect(panel.getByRole('region',{name:'over 2 sportsbook comparison',exact:true})).toContainText('Best live price: BetMGM +120');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await panel.scrollIntoViewIfNeeded();
  const finalToggle=page.getByRole('region',{name:'Research slip'}).getByRole('button',{name:'My Slip'});
  if(await finalToggle.getAttribute('aria-expanded')==='true')await finalToggle.click();
  await page.screenshot({path:test.info().outputPath(`exact-line-${width}.png`),fullPage:true});
  expect(calls.some(c=>c.sportsbook==='DraftKings'&&c.offer_line==='2.5'&&c.side==='under')).toBe(true);
  expect(errors).toEqual([]);expect(blocked).toEqual([]);
});
