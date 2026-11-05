"""Private actual-image source/restore auth contract, isolated fixtures only."""
import http.client,json,os,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()));sys.path.insert(0,'/fixture')
from sqlalchemy import create_engine
from production_stack_fixture import target_url,verify_physical_target,fingerprint,fixture_id
from fastapi.testclient import TestClient
import httpx
import requests
from app.main import app
from app.config import settings
mode=os.environ['PROPPULSE_IMAGE_AUTH_MODE'];assert mode in {'source','restore'}
target=target_url(os.environ['DATABASE_URL']);engine=create_engine(target)
with engine.connect() as conn:verify_physical_target(conn,target)
assert settings.production and not settings.LIVE_REFRESH_ENABLED
statefile=Path('/proof/auth-state.json')
starts=fingerprint(engine);attempts=[]
def forbidden(*a,**kw):attempts.append(True);raise RuntimeError('External HTTP forbidden')
async def forbidden_async(*a,**kw):return forbidden()
with patch.object(httpx.HTTPTransport,'handle_request',forbidden),patch.object(httpx.AsyncHTTPTransport,'handle_async_request',forbidden_async),patch.object(http.client.HTTPConnection,'connect',forbidden),patch.object(requests.sessions.Session,'request',forbidden):
    with TestClient(app,base_url='https://api.proppulse.test:3443') as client:
        assert client.get('/health').status_code==200
        assert client.get('/ready').json()=={'status':'ready'}
        assert fingerprint(engine)==starts
        origin=settings.CORS_ORIGINS[0]
        def proof():return {'Origin':origin,'X-CSRF-Token':client.get('/auth/csrf').json()['csrf_token']}
        body={'email':'image-regression@example.com','password':os.environ['PROPPULSE_IMAGE_AUTH_PASSWORD']}
        if mode=='source':
            response=client.post('/auth/register',json=body,headers=proof())
            assert response.status_code==200 and response.json()=={'ok':True}
            cookie=response.headers['set-cookie'];assert 'Secure' in cookie and 'HttpOnly' in cookie and 'Domain=' not in cookie
            user=client.get('/users/me').json()
            choice={'sportsbook':'FanDuel','line':20.5,'side':'under'}
            saved=client.post('/users/me/saved/selections/'+fixture_id(300),json=choice,headers=proof())
            assert saved.status_code==200
            identifier=saved.json()['id']
            assert client.post('/users/me/saved/selections/'+identifier+'/slip',headers=proof()).status_code==200
            assert client.patch('/users/me/saved/selections/'+fixture_id(451),json=choice,headers=proof()).status_code==404
            expired=client.post('/interactions/'+fixture_id(311),json={'action':'add_to_slip','side':'under','sportsbook':'FanDuel','line':20.5},headers=proof())
            assert expired.status_code==400
            saved_body=client.get('/users/me/saved').json();slip_body=client.get('/users/me/slip').json()
            assert any(s['id']==identifier and s['side']=='under' for s in saved_body['selections'])
            item=slip_body['slip']['items'][0];assert item['side']=='under' and item['selection']['sportsbook']=='FanDuel' and item['selection']['line']==20.5
            statefile.write_text(json.dumps({'user_id':user['id'],'saved_id':identifier,'cookie':client.cookies.get('__Host-proppulse_session'),'saved':saved_body,'slip':slip_body}),encoding='utf-8')
            print(json.dumps({'production_lifespan':'passed','health_ready':200,'startup_rows_unchanged':True,'actual_registration_secure_cookie':'passed','exact_saved_and_slip_under_20_5':'persisted','cross_owner_edit':404,'expired_offer_rejected':400,'external_http_attempts':len(attempts)}))
        else:
            source=json.loads(statefile.read_text())
            client.cookies.set('__Host-proppulse_session',source['cookie'],domain='api.proppulse.test',path='/')
            assert client.get('/users/me').json()['id']==source['user_id']
            assert client.get('/users/me/saved').json()['selections'][0]['id']==source['saved_id']
            slip=client.get('/users/me/slip').json()['slip']['items'][0]
            assert slip['side']=='under' and slip['selection']['line']==20.5 and slip['selection']['sportsbook']=='FanDuel'
            client.cookies.clear()
            response=client.post('/auth/login',json=body,headers=proof())
            assert response.status_code==200 and response.json()=={'ok':True}
            assert client.get('/users/me').json()['id']==source['user_id']
            assert client.post('/auth/logout',headers=proof()).json()=={'ok':True}
            assert client.get('/users/me').status_code==401
            assert fingerprint(engine)==starts
            print(json.dumps({'production_lifespan':'passed','health_ready':200,'startup_login_logout_rows_unchanged':True,'existing_source_session_after_restore':'passed','retained_password_hash_login':'passed','exact_saved_and_slip_under_20_5':'preserved','logout':401,'external_http_attempts':len(attempts)}))
assert not attempts
engine.dispose()
