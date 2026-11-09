/* Actual Chrome + HTTPS requests against only the owned local rehearsal. */
const assert=require('assert'), fs=require('fs'), path=require('path'), https=require('https'), crypto=require('crypto');
const control=require('../../backend/tests/oracle_deployment_rehearsal.cjs');
const {STATE,compose,docker,ownership,ready}=control;
const {chromium}=require('@playwright/test');
const ca=fs.readFileSync(path.join(STATE,'cloudflare_client_ca.pem'));
const password=JSON.parse(fs.readFileSync(path.join(STATE,'browser.json'))).password;
const run=Date.now(), emailA='oracle-a-'+run+'@example.com', emailB='oracle-b-'+run+'@example.com';
const agent=new https.Agent({keepAlive:true,maxSockets:16});
const prop='00000000-0000-0000-0000-00000000012c';
function request(route, options={}) {
  return new Promise((resolve,reject)=>{
    const data=options.body === undefined ? undefined:JSON.stringify(options.body);
    const req=https.request({host:'127.0.0.1',port:options.direct?3444:443,servername:'api.example.com',ca,
      agent:options.direct?false:agent,
      cert:options.client?fs.readFileSync(path.join(STATE,'client_cert.pem')):undefined,
      key:options.client?fs.readFileSync(path.join(STATE,'client_key.pem')):undefined,
      method:options.method||'GET',path:route,headers:{Host:'api.example.com',
        ...(data?{'Content-Type':'application/json','Content-Length':Buffer.byteLength(data)}:{}),...options.headers},
      timeout:20000},res=>{const chunks=[];res.on('data',b=>chunks.push(b));res.on('end',()=>resolve({
        status:res.statusCode,headers:res.headers,text:Buffer.concat(chunks).toString()
      }));});
    req.on('error',reject);req.on('timeout',()=>req.destroy(new Error('Local HTTPS timeout')));
    req.end(data);
  });
}
function session() {
  const jar={};
  async function call(route,options={}) {
    const r=await request(route,{...options,headers:{Cookie:Object.entries(jar).map(([k,v])=>k+'='+v).join('; '),...options.headers}});
    for(const value of r.headers['set-cookie']||[]){const [key,...rest]=value.split(';')[0].split('=');jar[key]=rest.join('=');}
    return r;
  }
  async function proof(){const r=await call('/auth/csrf');assert.equal(r.status,200);return JSON.parse(r.text).csrf_token;}
  async function mutate(route,body,method='POST'){
    return call(route,{method,body,headers:{Origin:'https://app.example.com','X-CSRF-Token':await proof()}});
  }
  return {call,proof,mutate};
}
async function main() {
  ownership();
  // A retry must not inherit credential budgets consumed by an earlier probe.
  compose('restart','backend','gateway');await ready('backend');await ready('gateway');
  // Wait for npm/tooling startup without making any public request.
  let up=false;
  for(let i=0;i<180;i++){
    try{if((await request('/health')).status===200){up=true;break;}}catch{}
    await new Promise(r=>setTimeout(r,500));
  }
  assert(up,'Local HTTPS API not ready');
  const id=compose('ps','-q','frontend');
  let frontend=false;
  for(let i=0;i<180;i++){
    const logs=docker(['logs',id]);
    if(logs.includes('Ready on http://')){frontend=true;break;}
    await new Promise(r=>setTimeout(r,500));
  }
  assert(frontend,'Local Workers runtime not ready');
  const a=session(), b=session();
  const oldProof=await a.proof();
  const registered=await a.mutate('/auth/register',{email:emailA,password,username:'Oracle rehearsal A'});
  assert.equal(registered.status,200);
  const cookie=registered.headers['set-cookie'].join(';');
  assert(cookie.includes('__Host-proppulse_session=')&&cookie.includes('Secure')&&cookie.includes('HttpOnly')&&cookie.includes('SameSite=lax')&&!cookie.includes('Domain='));
  assert.equal((await a.call('/users/me')).status,200);
  assert.equal((await a.call('/auth/logout',{method:'POST',headers:{Origin:'https://app.example.com','X-CSRF-Token':oldProof}})).status,403);
  assert.equal((await a.call('/auth/logout',{method:'POST',headers:{Origin:'https://untrusted.example.com','X-CSRF-Token':await a.proof()}})).status,403);
  assert.equal((await a.call('/auth/logout',{method:'POST',headers:{Origin:'https://app.example.com'}})).status,403);
  const saved=await a.mutate('/users/me/saved/selections/'+prop,{sportsbook:'FanDuel',line:20.5,side:'under'});
  assert.equal(saved.status,200);const selection=JSON.parse(saved.text).id;
  assert.equal((await a.mutate('/users/me/saved/selections/'+selection+'/slip')).status,200);
  assert.equal((await b.mutate('/auth/register',{email:emailB,password})).status,200);
  assert.equal((await b.mutate('/users/me/saved/selections/'+selection,{side:'over',sportsbook:'FanDuel',line:20.5},'PATCH')).status,404);
  assert.equal(JSON.parse((await b.call('/users/me/saved')).text).selections.length,0);
  assert.equal((await b.mutate('/auth/logout')).status,200);
  assert.equal((await b.call('/users/me')).status,401);
  const allowed=await request('/auth/csrf',{method:'OPTIONS',headers:{Origin:'https://app.example.com','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type,x-csrf-token'}});
  assert.equal(allowed.status,200);assert.equal(allowed.headers['access-control-allow-origin'],'https://app.example.com');
  assert.equal(allowed.headers['access-control-allow-credentials'],'true');
  const forbidden=await request('/auth/csrf',{method:'OPTIONS',headers:{Origin:'https://untrusted.example.com','Access-Control-Request-Method':'POST'}});
  assert.equal(forbidden.status,400);
  assert([400,403].includes((await request('/health',{direct:true})).status));
  assert.equal((await request('/health',{direct:true,client:true,headers:{'CF-Connecting-IP':'198.51.100.30','X-Forwarded-For':'198.51.100.31'}})).status,403);
  const large=await request('/auth/login',{method:'POST',body:{oversized:'x'.repeat(1024*1024+1)}});
  assert.equal(large.status,413);
  const x509=new crypto.X509Certificate(fs.readFileSync(path.join(STATE,'origin_cert.pem')));
  const spki=crypto.createHash('sha256').update(x509.publicKey.export({format:'der',type:'spki'})).digest('base64');
  const browser=await chromium.launch({channel:'chrome',headless:true,args:[
    '--host-resolver-rules=MAP app.example.com 127.0.0.1, MAP api.example.com 127.0.0.1',
    '--ignore-certificate-errors-spki-list='+spki,'--no-proxy-server','--disable-background-networking']});
  try {
    const context=await browser.newContext(), page=await context.newPage(), errors=[],blocked=[];
    page.on('pageerror',e=>errors.push(e.message));
    await context.route('**/*',route=>{
      if(['https://app.example.com','https://api.example.com'].includes(new URL(route.request().url()).origin))return route.continue();
      blocked.push(new URL(route.request().url()).origin);return route.abort();
    });
    await page.goto('https://app.example.com/login');
    await page.getByLabel(/email/i).fill(emailA);
    await page.getByLabel(/password/i).fill(password);
    await page.getByRole('button',{name:/sign in|log in/i}).click();
    await page.waitForURL(url=>!url.pathname.startsWith('/login'),{timeout:30000});
    await page.goto('https://app.example.com/saved');
    await page.getByText('Invented Oracle rehearsal player',{exact:false}).first().waitFor({timeout:15000});
    const current=await page.evaluate(async()=>{const r=await fetch('https://api.example.com/users/me',{credentials:'include'});return r.status;});
    assert.equal(current,200);
    const browserCookies=await context.cookies('https://api.example.com');
    assert(browserCookies.find(c=>c.name==='__Host-proppulse_session'&&c.httpOnly&&c.secure&&c.sameSite==='Lax'));
    await page.reload();
    await page.getByText('Invented Oracle rehearsal player',{exact:false}).first().waitFor();
    const picked=await page.evaluate(async()=>{const r=await fetch('https://api.example.com/users/me/slip',{credentials:'include'});return r.json();});
    assert.equal(picked.slip.items[0].side,'under');assert.equal(picked.slip.items[0].selection.line,20.5);
    compose('restart','db');await ready('db');
    // App readiness reconnects after the private PostgreSQL restart.
    for(let i=0;i<60;i++){if((await request('/ready')).status===200)break;await new Promise(r=>setTimeout(r,500));}
    assert.equal((await request('/ready')).status,200);
    await page.reload();await page.getByText('Invented Oracle rehearsal player',{exact:false}).first().waitFor();
    const logout=await page.evaluate(async()=>{
      const proof=await (await fetch('https://api.example.com/auth/csrf',{credentials:'include'})).json();
      const r=await fetch('https://api.example.com/auth/logout',{method:'POST',credentials:'include',
        headers:{'X-CSRF-Token':proof.csrf_token,'Content-Type':'application/json'}});
      return r.status;
    });
    assert.equal(logout,200);
    assert.equal(await page.evaluate(async()=>(await fetch('https://api.example.com/users/me',{credentials:'include'})).status),401);
    assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);
    await context.close();
  } finally {await browser.close();}
  // Isolate gateway quotas from the separately tested process-local backstop.
  compose('restart','backend','gateway');await ready('backend');await ready('gateway');
  const auth=[];
  for(let n=0;n<12;n++)auth.push(await request('/auth/login',{method:'POST',body:{},headers:{
    'CF-Connecting-IP':'198.51.100.'+(n+1),'X-Forwarded-For':'203.0.113.'+(n+1),Forwarded:'for=198.51.100.'+(n+1)}}));
  assert(auth.filter(r=>r.status===429).length>=2);
  assert(auth.filter(r=>r.status===429).every(r=>r.headers['retry-after']==='60'));
  const api=await Promise.all(Array.from({length:100},()=>request('/health')));
  assert(api.some(r=>r.status===429));assert(api.filter(r=>r.status===429).every(r=>r.headers['retry-after']==='60'));
  const sentinel='OracleRehearsalLogSentinel'+crypto.randomBytes(8).toString('hex');
  await request('/health',{headers:{Cookie:sentinel,Authorization:sentinel,'X-CSRF-Token':sentinel}});
  for(const name of ['gateway','backend','cloudflare','db']){
    const logs=docker(['logs',compose('ps','-q',name)]);
    assert(!logs.includes(sentinel),'Header leaked into '+name+' logs');
    for(const secret of ['db_admin_password','db_owner_password','db_app_password','jwt_secret']){
      assert(!logs.includes(fs.readFileSync(path.join(STATE,secret),'utf8')),'Secret leaked into logs');
    }
  }
  for(const name of ['backend','db','gateway']){
    const info=JSON.parse(docker(['inspect',compose('ps','-q',name)]))[0];
    assert(info.HostConfig.ReadonlyRootfs);
    assert(info.HostConfig.CapDrop.includes('ALL'));
    assert(info.HostConfig.SecurityOpt.includes('no-new-privileges:true')||info.HostConfig.SecurityOpt.includes('no-new-privileges'));
    if(name!=='gateway')assert(!Object.values(info.HostConfig.PortBindings||{}).length);
    assert.equal(info.Config.User,name==='db'?'70:70':name==='backend'?'10001:10001':'101:101');
    assert(info.HostConfig.Memory>0&&info.HostConfig.NanoCpus>0);
  }
  const report={local_https_mtls:true,real_chrome_workers_auth:true,session_restore:true,csrf_rejections:true,
    saved_under_20_5_and_slip:true,cross_account:404,postgres_restart:true,cors_preflight:true,
    direct_origin_and_spoof_rejection:true,body_limit:413,auth_and_api_429_retry_after:true,
    secret_log_redaction:true,nonroot_readonly_caps_resources:true,public_tls_verified:false};
  fs.writeFileSync(path.join(STATE,'verification.json'),JSON.stringify(report,null,2));
  agent.destroy();
  console.log(JSON.stringify(report));
}
main().catch(e=>{agent.destroy();console.error(e.message);process.exitCode=1;});
