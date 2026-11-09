/* Owns only the pp-oracle-rehearsal Compose project and ignored fixture state. */
const fs = require('fs'), path = require('path'), cp = require('child_process'), crypto = require('crypto');
const ROOT = path.resolve(__dirname, '../..');
const STATE = path.join(ROOT, 'backend/data/odds_runs/oracle-deployment-prep');
const PROJECT = 'pp-oracle-rehearsal';
const BASE = path.join(ROOT, 'deploy/oracle/compose.yml');
const slashes = p => p.replaceAll('\\', '/');
function docker(args) {
  const r = cp.spawnSync('docker', args, {cwd: ROOT, encoding: 'utf8', timeout: 300000, maxBuffer: 16*1024*1024});
  if (r.status !== 0) {
    if (fs.existsSync(STATE)) fs.writeFileSync(path.join(STATE, 'docker-error.log'), r.stderr || 'Docker command failed');
    throw new Error('Docker operation failed; inspect ignored private docker-error.log');
  }
  return r.stdout.trim();
}
function compose(...args) {
  return docker(['compose','--project-name',PROJECT,'--env-file',path.join(STATE,'config.env'),
    '-f',BASE,'-f',path.join(STATE,'local.compose.json'),...args]);
}
function resources(kind) {
  return docker([kind,'ls',...(kind==='container'?['-a']:[]),'--filter','label=com.docker.compose.project='+PROJECT,
    '--format',kind==='network'?'{{.ID}}':kind==='volume'?'{{.Name}}':'{{.ID}}']).split('\n').filter(Boolean);
}
function ownership() {
  if (!fs.existsSync(path.join(STATE,'owner.json')) ||
      JSON.parse(fs.readFileSync(path.join(STATE,'owner.json'))).project !== PROJECT) throw new Error('Missing rehearsal ownership');
  for (const kind of ['container','network','volume']) for(const id of resources(kind)) {
    const r = JSON.parse(docker([kind,'inspect',id]))[0], labels = kind==='container'?r.Config.Labels:r.Labels;
    if(labels['com.docker.compose.project'] !== PROJECT) throw new Error('Refusing unowned resource');
  }
}
function prepare() {
  if(fs.existsSync(STATE)) throw new Error('Rehearsal state exists; do not overwrite private evidence');
  for(const kind of ['container','network','volume']) if(resources(kind).length) throw new Error('Project resources already exist');
  fs.mkdirSync(path.join(STATE,'gateway'),{recursive:true});
  fs.writeFileSync(path.join(STATE,'owner.json'),JSON.stringify({project:PROJECT,created:new Date().toISOString()}));
  const write=(name,data)=>fs.writeFileSync(path.join(STATE,name),data,{mode:0o600});
  const token=()=>crypto.randomBytes(36).toString('base64url');
  for(const name of ['db_admin_password','db_owner_password','db_app_password','jwt_secret'])write(name,token());
  const owner=fs.readFileSync(path.join(STATE,'db_owner_password'),'utf8'), app=fs.readFileSync(path.join(STATE,'db_app_password'),'utf8');
  write('migration_database_url','postgresql://pp_owner:'+owner+'@db:5432/proppulse_rehearsal');
  write('app_database_url','postgresql://pp_app:'+app+'@db:5432/proppulse_rehearsal');
  write('browser.json',JSON.stringify({password:token()}));
  write('config.env',Object.entries({
    BACKEND_IMAGE:'proppulse-oracle-backend:arm64',POSTGRES_IMAGE:'proppulse-assessment-postgres:arm64',
    GATEWAY_IMAGE:'nginx:stable-alpine@sha256:47928bf67eb62a1863cb08d9ecb52d3e704304ba614eaee17884204677702951',
    SECRETS_DIR:slashes(STATE),NGINX_CONFIG_DIR:slashes(path.join(STATE,'gateway')),
    PG_DATABASE:'proppulse_rehearsal',CORS_ORIGINS:'["https://app.example.com"]',
    GATEWAY_BIND:'127.0.0.1',GATEWAY_PORT:'3444',API_SUBNET:'10.78.0.0/24',GATEWAY_IP:'10.78.0.2'
  }).map(([k,v])=>k+'='+v).join('\n')+'\n');
  fs.copyFileSync(path.join(ROOT,'deploy/oracle/nginx/nginx.conf'),path.join(STATE,'gateway/nginx.conf'));
  write('gateway/cloudflare.conf','geo $realip_remote_addr $cloudflare_peer { default 0; 10.79.0.2 1; }\nset_real_ip_from 10.79.0.2;\n');
  const image='proppulse-oracle-backend:arm64';
  docker(['run','--rm','--platform','linux/arm64','--network','none','--read-only','--cap-drop','ALL',
    '-v',slashes(STATE)+':/proof','-v',slashes(path.join(__dirname,'oracle_deployment_fixture.py'))+':/fixture.py:ro',
    image,'python','/fixture.py','certificates']);
  // Public system CA bundle for workerd in the slim Node tooling container.
  write('system-ca.pem',docker(['run','--rm','--network','none','--entrypoint','cat',
    'proppulse-assessment-postgres:arm64','/etc/ssl/certs/ca-certificates.crt'])+'\n');
  write('edge.conf',`worker_processes 2;
pid /tmp/edge.pid; error_log /dev/null crit;
events { worker_connections 512; }
http {
  access_log off; client_max_body_size 2m;
  client_body_temp_path /tmp/body; proxy_temp_path /tmp/proxy;
  fastcgi_temp_path /tmp/fastcgi; uwsgi_temp_path /tmp/uwsgi; scgi_temp_path /tmp/scgi;
  ssl_certificate /fixture/origin_cert.pem; ssl_certificate_key /fixture/origin_key.pem;
  upstream oracle_backend { server gateway:8443; keepalive 16; }
  server { listen 8443 ssl; server_name app.example.com;
    location / { proxy_pass http://frontend:3199; proxy_set_header Host $host; } }
  server { listen 8443 ssl; server_name api.example.com;
    location / {
      proxy_pass https://oracle_backend; proxy_ssl_server_name on; proxy_ssl_name api.example.com;
      proxy_http_version 1.1; proxy_set_header Connection "";
      proxy_ssl_verify on; proxy_ssl_trusted_certificate /fixture/cloudflare_client_ca.pem;
      proxy_ssl_certificate /fixture/client_cert.pem; proxy_ssl_certificate_key /fixture/client_key.pem;
      proxy_set_header Host api.example.com;
      proxy_set_header CF-Connecting-IP $remote_addr;
      proxy_set_header X-Forwarded-For "";
      proxy_set_header Forwarded "";
    }
  }
}\n`);
  const gatewayImage='nginx:stable-alpine@sha256:47928bf67eb62a1863cb08d9ecb52d3e704304ba614eaee17884204677702951';
  write('local.compose.json',JSON.stringify({
    services:{
      fixture:{extends:{file:slashes(BASE),service:'migrate'},
        entrypoint:['python','/fixture/oracle_deployment_fixture.py','seed'],
        environment:{ORACLE_REHEARSAL_ACK:'invented-disposable-oracle-only'},
        volumes:[slashes(path.join(__dirname,'oracle_deployment_fixture.py'))+':/fixture/oracle_deployment_fixture.py:ro']},
      frontend:{image:'node:22-bookworm-slim',working_dir:'/app',
        command:['sh','-c','npm ci --no-audit --no-fund && npx wrangler dev --local --ip 0.0.0.0 --port 3199'],
        environment:{WRANGLER_SEND_METRICS:'false'},networks:{edge:{ipv4_address:'10.79.0.4'}},
        volumes:[slashes(path.join(ROOT,'frontend'))+':/app','frontend_modules:/app/node_modules',
          slashes(path.join(STATE,'system-ca.pem'))+':/etc/ssl/certs/ca-certificates.crt:ro']},
      gateway:{networks:{edge:{ipv4_address:'10.79.0.3'}}},
      cloudflare:{image:gatewayImage,platform:'linux/arm64',user:'101:101',read_only:true,cap_drop:['ALL'],
        security_opt:['no-new-privileges:true'],entrypoint:['nginx','-g','daemon off;'],
        ports:['127.0.0.1:443:8443'],tmpfs:['/tmp:rw,nosuid,nodev,size=32m,uid=101,gid=101'],
        volumes:[slashes(path.join(STATE,'edge.conf'))+':/etc/nginx/nginx.conf:ro',slashes(STATE)+':/fixture:ro'],
        networks:{edge:{ipv4_address:'10.79.0.2'}},depends_on:['frontend','gateway']}
    },networks:{edge:{ipam:{config:[{subnet:'10.79.0.0/24'}]}}},volumes:{frontend_modules:{}}
  },null,2));
  const config=JSON.parse(compose('config','--format','json'));
  fs.writeFileSync(path.join(STATE,'resolved-compose.json'),JSON.stringify(config,null,2));
  for(const name of ['backend','db']) if(config.services[name].ports?.length) throw new Error('Private service exposes a port');
  console.log('Prepared only ignored disposable secrets, local TLS and override; production Compose validated');
}
async function ready(service) {
  for(let i=0;i<120;i++){
    const id=compose('ps','-q',service);
    if(id){const state=JSON.parse(docker(['inspect',id]))[0].State;
      if(state.Health?.Status==='healthy')return;
      if(!state.Running)throw new Error(service+' exited; inspect private container logs');
    }
    await new Promise(r=>setTimeout(r,500));
  }
  throw new Error(service+' did not become ready');
}
async function start() {
  ownership();
  compose('--profile','tools','run','--rm','volume-init');
  compose('up','-d','db'); await ready('db');
  compose('--profile','tools','run','--rm','bootstrap');
  compose('--profile','tools','run','--rm','migrate');
  compose('--profile','tools','run','--rm','fixture');
  compose('up','-d','backend','gateway','frontend','cloudflare'); await ready('backend'); await ready('gateway');
  console.log('Actual production services started with local edge emulation; no cloud resources');
}
function cleanup() {
  ownership();
  compose('--profile','tools','down','--volumes','--remove-orphans');
  console.log('Removed only owned rehearsal containers, networks and disposable volumes; private evidence retained');
}
function backup() {
  ownership();
  const id=compose('ps','-q','db');
  if(!id)throw new Error('Rehearsal database is not running');
  // Keep custom-format dump bytes binary; never pass them through a text shell.
  const result=cp.spawnSync('docker',['exec',id,'pg_dump','-U','postgres','-d','proppulse_rehearsal',
    '-Fc','--no-owner','--no-acl'],{cwd:ROOT,timeout:60000,maxBuffer:16*1024*1024});
  if(result.status!==0)throw new Error('Rehearsal backup failed');
  fs.writeFileSync(path.join(STATE,'rehearsal.dump'),result.stdout,{mode:0o600});
  const catalog=cp.spawnSync('docker',['exec','-i',id,'pg_restore','--list'],
    {input:result.stdout,timeout:60000,maxBuffer:16*1024*1024});
  if(catalog.status!==0)throw new Error('Backup archive verification failed');
  fs.writeFileSync(path.join(STATE,'backup-catalog.txt'),catalog.stdout,{mode:0o600});
  console.log('Synthetic rehearsal logical backup captured; archive catalog verified');
}
module.exports={ROOT,STATE,PROJECT,docker,compose,ownership,ready};
if(require.main===module)(async()=>{
  const action=process.argv[2];
  if(action==='prepare')prepare();else if(action==='start')await start();else if(action==='backup')backup();else if(action==='cleanup')cleanup();
  else throw new Error('Choose prepare, start, backup or cleanup');
})().catch(e=>{console.error(e.message);process.exitCode=1;});
