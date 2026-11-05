const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {loadSource} = require('./load-source.cjs');

test('cookie API bootstraps CSRF once, credentials every request, refreshes proof across auth transitions', async t => {
  const {api} = loadSource('lib/api.ts');
  const calls = [];
  let proofs = 0;
  t.mock.method(global, 'fetch', async (url, options) => {
    calls.push({url, options});
    return {ok:true, json:async () => url.endsWith('/auth/csrf') ? {csrf_token:`proof-${++proofs}`} : {ok:true}};
  });
  await api.getMe();
  await Promise.all([api.interact('p','save'), api.followPlayer('player')]);
  assert.equal(proofs, 1, 'concurrent writes share the CSRF bootstrap');
  await api.login('fixture@example.invalid','fixture-password');
  await api.updatePreferences({fav_sports:['NBA']});
  assert.equal(proofs, 2, 'login rotates cached proof');
  await api.logout();
  await api.register('new@example.invalid','fixture-password');
  assert.equal(proofs, 3, 'logout rotates cached proof');
  await api.removeFromSlip('p');
  assert.equal(proofs, 4, 'registration rotates cached proof');
  for (const {url,options} of calls) {
    assert.equal(options.credentials, 'include');
    assert.equal(options.cache, 'no-store');
    assert.equal(options.headers.Authorization, undefined);
    if (options.method) assert.match(options.headers['X-CSRF-Token'], /^proof-/);
    else assert.equal(options.headers['X-CSRF-Token'], undefined, url);
  }
});

test('failed CSRF bootstrap sends no mutation and a subsequent retry can recover', async t => {
  const {api} = loadSource('lib/api.ts');
  const calls=[];
  t.mock.method(global,'fetch',async (url) => { calls.push(url); return {ok:false,status:503,json:async()=>({detail:'Unavailable'})}; });
  await assert.rejects(api.logout(), /Unavailable/);
  assert.equal(calls.length,1);
  assert.ok(calls[0].endsWith('/auth/csrf'));
  t.mock.method(global,'fetch',async url=>({ok:true,json:async()=>url.endsWith('/auth/csrf')?{csrf_token:'recovered'}:{ok:true}}));
  await api.logout();
});

test('confirmed anonymous clears personal UI state; temporary failures and failed logout preserve authenticated state', async () => {
  const {ApiError} = loadSource('lib/api.ts');
  const user={id:'fixture-user',email:'fixture@example.invalid'};
  const api={getMe:async()=>user,logout:async()=>{throw new Error('Temporary failure');}};
  const saved={setState(state){this.state=state;}};
  const slip={setState(state){this.state=state;}};
  const auth=loadSource('store/auth.ts', {'@/lib/api':{api,ApiError},'@/store/savedProps':{useSavedProps:saved},'@/store/slip':{useSlip:slip}});
  await auth.restoreSession();
  assert.equal(auth.useAuth.getState().status,'authenticated');
  api.getMe=async()=>{throw new ApiError(503,'Temporary outage');};
  await assert.rejects(auth.restoreSession());
  assert.equal(auth.useAuth.getState().user,user);
  await assert.rejects(auth.signOut());
  assert.equal(auth.useAuth.getState().user,user);
  assert.equal(saved.state,undefined);
  api.getMe=async()=>{throw new ApiError(401,'Login required');};
  assert.equal(await auth.restoreSession(),null);
  assert.equal(auth.useAuth.getState().status,'anonymous');
  assert.deepEqual(saved.state.ids,{});
  assert.deepEqual(slip.state.items,[]);
});

test('session expiry during an in-flight restore cannot restore a previous account', async()=>{
  const {ApiError}=loadSource('lib/api.ts');
  let finish;
  const api={getMe:()=>new Promise(resolve=>{finish=resolve;})};
  const auth=loadSource('store/auth.ts',{'@/lib/api':{api,ApiError}});
  const restore=auth.restoreSession();
  auth.clearSession();
  finish({id:'stale-account'});
  assert.equal(await restore,null);
  assert.equal(auth.useAuth.getState().status,'anonymous');
});

test('application has no browser-readable bearer storage or bearer transport; layout stays server-rendered',()=>{
  const root=path.resolve(__dirname,'../src');
  function files(dir){return fs.readdirSync(dir,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?files(path.join(dir,entry.name)):[path.join(dir,entry.name)]);}
  for(const file of files(root).filter(file=>/\.tsx?$/.test(file))){
    const source=fs.readFileSync(file,'utf8');
    assert.doesNotMatch(source,/(?:localStorage|sessionStorage)\.(?:getItem|setItem)\([^)]*(?:token|jwt)|access_token|Authorization.*Bearer/,file);
  }
  assert.doesNotMatch(fs.readFileSync(path.join(root,'app/layout.tsx'),'utf8'),/^['"]use client['"];?/m);
});
