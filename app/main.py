import asyncio, hashlib, hmac, json, os, secrets, shutil, subprocess, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .database import init_db, fetch, fetch_one, execute

ROOT = Path(__file__).resolve().parent.parent
GENERATED = ROOT / 'generated' / 'apks'
ANDROID = ROOT / 'android' / 'agent'
GENERATED.mkdir(parents=True, exist_ok=True)

app = FastAPI(title=settings.app_name)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, same_site='lax', https_only=False)
templates = Jinja2Templates(directory=str(ROOT / 'templates'))
app.mount('/static', StaticFiles(directory=str(ROOT / 'static')), name='static')

class Hub:
    def __init__(self):
        self.browsers = set()
        self.devices = {}
    async def broadcast(self, payload):
        dead = []
        text = json.dumps(payload)
        for ws in list(self.browsers):
            try: await ws.send_text(text)
            except Exception: dead.append(ws)
        for ws in dead: self.browsers.discard(ws)
    async def send_device(self, device_id, payload):
        ws = self.devices.get(str(device_id))
        if ws:
            try: await ws.send_text(json.dumps(payload)); return True
            except Exception: self.devices.pop(str(device_id), None)
        return False
hub = Hub()


def now(): return datetime.now(timezone.utc).isoformat()

def public_base_url(request: Request):
    host = request.headers.get('x-forwarded-host') or request.headers.get('host')
    proto = request.headers.get('x-forwarded-proto') or request.url.scheme
    if host: return f'{proto}://{host}'.rstrip('/')
    return str(request.base_url).rstrip('/')

def hash_secret(value): return hashlib.sha256(value.encode()).hexdigest()

def make_initial_hash(value):
    return hash_secret(value + settings.session_secret)

def ensure_admin():
    row = fetch_one('SELECT id FROM users WHERE username=?', (settings.admin_username,))
    if not row: execute('INSERT INTO users(username,password_hash) VALUES (?,?)', (settings.admin_username, make_initial_hash(settings.admin_password)))

def logged_in(request: Request): return bool(request.session.get('admin_id'))

def require_api(request: Request):
    if not logged_in(request): raise HTTPException(401, 'Authentication required')

def log_event(device_id, kind, detail=''):
    execute('INSERT INTO logs(device_id,type,detail) VALUES (?,?,?)', (device_id, kind, detail))

@app.on_event('startup')
async def startup():
    init_db(); ensure_admin()
    if settings.demo_mode:
        existing = fetch_one('SELECT id FROM devices WHERE demo=1 LIMIT 1')
        if not existing:
            for i, status in enumerate(('ONLINE','OFFLINE','ONLINE'), 1):
                execute('INSERT INTO devices(device_uid,name,model,manufacturer,android_version,battery,status,network,ip,last_seen,demo) VALUES (?,?,?,?,?,?,?,?,?,?,1)', (f'DEMO-{i:02}', f'Demo Device {i}', 'Pixel Demo', 'Google', '14', 90-i*17, status, 'Wi-Fi', f'192.0.2.{10+i}', now(),))
            for row in fetch('SELECT id FROM devices WHERE demo=1'):
                log_event(row['id'],'Demo initialized','Simulated device created')
    asyncio.create_task(demo_loop())

async def demo_loop():
    while True:
        await asyncio.sleep(6)
        if not settings.demo_mode: continue
        rows = fetch('SELECT * FROM devices WHERE demo=1')
        for row in rows:
            battery = max(10, (row['battery'] or 50) - secrets.choice([0,1,2]))
            status = 'ONLINE' if row['status'] != 'ONLINE' else 'OFFLINE'
            execute('UPDATE devices SET status=?, battery=?, last_seen=? WHERE id=?', (status,battery,now(),row['id']))
            log_event(row['id'], 'Device connected' if status=='ONLINE' else 'Device disconnected', 'DEMO')
        await hub.broadcast({'type':'devices.updated'})

@app.get('/', response_class=HTMLResponse)
async def home(request: Request): return RedirectResponse('/dashboard' if logged_in(request) else '/login')

@app.get('/login', response_class=HTMLResponse)
async def login_page(request: Request): return templates.TemplateResponse('login.html', {'request':request, 'error':None})

@app.post('/login', response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    row = fetch_one('SELECT id,password_hash FROM users WHERE username=?', (username.strip(),))
    if not row or not hmac.compare_digest(row['password_hash'], make_initial_hash(password)):
        return templates.TemplateResponse('login.html', {'request':request, 'error':'Credenciais inválidas.'}, status_code=401)
    request.session['admin_id'] = row['id']; request.session['username'] = username.strip()
    return RedirectResponse('/dashboard', status_code=303)

@app.post('/logout')
async def logout(request: Request):
    request.session.clear(); return RedirectResponse('/login', status_code=303)

@app.get('/{page}', response_class=HTMLResponse)
async def page(request: Request, page: str):
    require_api(request)
    allowed={'dashboard':'Geral','devices':'Dispositivos','device':'Dispositivo','apk_builder':'APK Builder','apks':'APKs','logs':'Logs','settings':'Definições'}
    key = page if page in allowed else 'dashboard'
    return templates.TemplateResponse('dashboard.html', {'request':request, 'page':key, 'title':allowed[key]})

@app.get('/health')
async def health():
    try: fetch_one('SELECT 1')
    except Exception as e: return JSONResponse({'ok':False,'database':False,'error':str(e)}, status_code=503)
    return {'ok':True,'database':True,'websocket':True,'port':settings.port,'environment':settings.app_env}

@app.get('/api/overview')
async def overview(request: Request):
    require_api(request)
    d=fetch('SELECT * FROM devices WHERE revoked=0 ORDER BY created_at DESC')
    commands=fetch('SELECT status FROM commands')
    return {'devices':[dict(x) for x in d], 'stats':{'total_devices':len(d),'online':sum(x['status']=='ONLINE' for x in d),'offline':sum(x['status']=='OFFLINE' for x in d),'commands':len(commands),'completed':sum(x['status']=='COMPLETED' for x in commands),'failed':sum(x['status']=='FAILED' for x in commands)}, 'logs':[dict(x) for x in fetch('SELECT * FROM logs ORDER BY id DESC LIMIT 20')]}

@app.get('/api/devices')
async def devices(request: Request):
    require_api(request); return [dict(x) for x in fetch('SELECT * FROM devices ORDER BY id DESC')]

@app.get('/api/devices/{device_id}')
async def device(request: Request, device_id: int):
    require_api(request); row=fetch_one('SELECT * FROM devices WHERE id=?',(device_id,))
    if not row: raise HTTPException(404,'Device not found')
    return {'device':dict(row),'messages':[dict(x) for x in fetch('SELECT * FROM messages WHERE device_id=? ORDER BY id DESC LIMIT 50',(device_id,))],'notifications':[dict(x) for x in fetch('SELECT * FROM notifications WHERE device_id=? ORDER BY id DESC LIMIT 50',(device_id,))],'commands':[dict(x) for x in fetch('SELECT * FROM commands WHERE device_id=? ORDER BY id DESC LIMIT 50',(device_id,))],'logs':[dict(x) for x in fetch('SELECT * FROM logs WHERE device_id=? ORDER BY id DESC LIMIT 100',(device_id,))]}

@app.post('/api/devices/{device_id}/rename')
async def rename(request: Request, device_id: int):
    require_api(request); data=await request.json(); name=str(data.get('name','')).strip()
    if not name: raise HTTPException(400,'Name required')
    execute('UPDATE devices SET name=? WHERE id=?',(name,device_id)); log_event(device_id,'Device renamed',name); await hub.broadcast({'type':'devices.updated'}); return {'ok':True}

@app.post('/api/devices/{device_id}/revoke')
async def revoke(request: Request, device_id: int):
    require_api(request); execute('UPDATE devices SET revoked=1,status="OFFLINE" WHERE id=?',(device_id,)); execute('UPDATE device_tokens SET revoked_at=? WHERE device_id=? AND revoked_at IS NULL',(now(),device_id)); log_event(device_id,'Device revoked','Administrative action'); await hub.send_device(device_id,{'type':'revoked'}); await hub.broadcast({'type':'devices.updated'}); return {'ok':True}

@app.post('/api/devices/{device_id}/command')
async def command(request: Request, device_id: int):
    require_api(request); data=await request.json(); kind=str(data.get('type','')).strip(); payload=data.get('payload',{})
    allowed={'lock','screen_start','screen_stop','toast','refresh'}
    if kind not in allowed: raise HTTPException(400,'Unsupported command')
    cid=execute('INSERT INTO commands(device_id,type,payload,status) VALUES (?,?,?,?,?)'.replace('?,?,?,?,?','?,?,?,?'),(device_id,kind,json.dumps(payload),'PENDING'))
    delivered=await hub.send_device(device_id,{'type':'command','command_id':cid,'command':kind,'payload':payload})
    if delivered: execute('UPDATE commands SET status=?,sent_at=? WHERE id=?',('SENT',now(),cid))
    else: execute('UPDATE commands SET status=? WHERE id=?',('FAILED',cid))
    log_event(device_id,'Command sent',kind); await hub.broadcast({'type':'command.updated','id':cid}); return {'id':cid,'status':'SENT' if delivered else 'FAILED'}

@app.post('/api/devices/{device_id}/message')
async def message(request: Request, device_id: int):
    require_api(request); data=await request.json(); content=str(data.get('content','')).strip()
    if not content: raise HTTPException(400,'Content required')
    mid=execute('INSERT INTO messages(device_id,content,status) VALUES (?,?,?)',(device_id,content,'PENDING'))
    delivered=await hub.send_device(device_id,{'type':'message','message_id':mid,'content':content})
    execute('UPDATE messages SET status=? WHERE id=?',('SENT' if delivered else 'FAILED',mid)); log_event(device_id,'Message sent',content[:120]); await hub.broadcast({'type':'messages.updated'}); return {'id':mid,'status':'SENT' if delivered else 'FAILED'}

@app.post('/api/enrollments')
async def enrollment(request: Request):
    require_api(request)
    token=secrets.token_urlsafe(32); code='-'.join([secrets.token_hex(2).upper(),secrets.token_hex(2).upper()])
    expires=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
    execute('INSERT INTO enrollment_requests(code,token_hash,expires_at) VALUES (?,?,?)',(code,hash_secret(token),expires))
    return {'code':code,'token':token,'expires_at':expires,'public_base_url':public_base_url(request)}

@app.post('/api/enroll')
async def enroll(request: Request):
    data=await request.json(); code=str(data.get('code','')).strip().upper(); token=str(data.get('token',''))
    req=fetch_one('SELECT * FROM enrollment_requests WHERE code=? AND used=0',(code,))
    if not req or req['token_hash']!=hash_secret(token): raise HTTPException(403,'Invalid enrollment')
    payload=data.get('device',{}); uid=str(payload.get('device_uid') or secrets.token_hex(12))
    existing=fetch_one('SELECT id FROM devices WHERE device_uid=?',(uid,))
    if existing: device_id=existing['id']
    else: device_id=execute('INSERT INTO devices(device_uid,name,model,manufacturer,android_version,agent_version,status,network,ip,last_seen) VALUES (?,?,?,?,?,?,?,?,?,?)',(uid,payload.get('name','Android device'),payload.get('model',''),payload.get('manufacturer',''),payload.get('android_version',''),payload.get('agent_version','1.0.0'),'ONLINE',payload.get('network',''),payload.get('ip',''),now()))
    device_token=secrets.token_urlsafe(32); execute('INSERT INTO device_tokens(device_id,token_hash) VALUES (?,?)',(device_id,hash_secret(device_token))); execute('UPDATE enrollment_requests SET used=1 WHERE id=?',(req['id'],)); log_event(device_id,'Enrollment completed','Authorized enrollment')
    await hub.broadcast({'type':'devices.updated'}); return {'device_id':device_id,'device_token':device_token,'public_base_url':public_base_url(request)}

@app.post('/api/apk/build')
async def build_apk(request: Request):
    require_api(request); started=now(); version=f'1.0.{int(time.time())%1000}'; build_id=execute('INSERT INTO apk_builds(name,version,status,started_at) VALUES (?,?,?,?)',('Android Agent',version,'BUILDING',started))
    gradle=shutil.which('gradle'); java=shutil.which('java'); sdk=os.getenv('ANDROID_HOME') or os.getenv('ANDROID_SDK_ROOT')
    error=''; out=''
    if not java or not (gradle or (ANDROID/'.gradlew').exists()) or not sdk:
        error='BUILD TOOLCHAIN UNAVAILABLE: Android SDK + Java + Gradle toolchain not detected.'
        execute('UPDATE apk_builds SET status=?,finished_at=?,error=? WHERE id=?',('BUILD TOOLCHAIN UNAVAILABLE',now(),error,build_id))
        return {'id':build_id,'status':'BUILD TOOLCHAIN UNAVAILABLE','error':error}
    try:
        cmd=[str(ANDROID/'.gradlew'),'assembleDebug'] if (ANDROID/'.gradlew').exists() else [gradle,'assembleDebug']
        subprocess.run(cmd,cwd=ANDROID,check=True,capture_output=True,text=True,timeout=300)
        candidates=list(ANDROID.glob('**/*.apk'))
        if not candidates: raise RuntimeError('Build completed without APK output')
        src=max(candidates,key=lambda p:p.stat().st_mtime); dst=GENERATED/f'android-agent-{version}.apk'; shutil.copy2(src,dst)
        execute('UPDATE apk_builds SET status=?,finished_at=?,path=?,size=? WHERE id=?',('READY',now(),str(dst.relative_to(ROOT)),dst.stat().st_size,build_id))
        out=str(dst.relative_to(ROOT))
    except Exception as e:
        error=str(e); execute('UPDATE apk_builds SET status=?,finished_at=?,error=? WHERE id=?',('FAILED',now(),error,build_id))
    await hub.broadcast({'type':'apks.updated'})
    return {'id':build_id,'status':'READY' if out else 'FAILED','path':out,'error':error}

@app.get('/api/apks')
async def apks(request: Request):
    require_api(request); return [dict(x) for x in fetch('SELECT * FROM apk_builds ORDER BY id DESC')]

@app.get('/api/logs')
async def logs(request: Request):
    require_api(request); return [dict(x) for x in fetch('SELECT * FROM logs ORDER BY id DESC LIMIT 500')]

@app.get('/api/settings')
async def get_settings(request: Request):
    require_api(request); return {'app_name':settings.app_name,'environment':settings.app_env,'version':'1.0.0','public_base_url':public_base_url(request),'detected':True,'port':80,'host':'0.0.0.0','demo_mode':settings.demo_mode}

@app.get('/downloads/{name}')
async def download(request: Request, name: str):
    require_api(request); path=(GENERATED/name).resolve()
    if GENERATED not in path.parents or not path.is_file(): raise HTTPException(404,'APK unavailable')
    return FileResponse(path, filename=path.name, media_type='application/vnd.android.package-archive')

@app.websocket('/ws/browser')
async def browser_ws(ws: WebSocket):
    await ws.accept()
    hub.browsers.add(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: hub.browsers.discard(ws)

@app.websocket('/ws/device/{device_id}')
async def device_ws(ws: WebSocket, device_id: int):
    token=ws.query_params.get('token','')
    row=fetch_one('SELECT * FROM device_tokens WHERE device_id=? AND token_hash=? AND revoked_at IS NULL',(device_id,hash_secret(token)))
    device=fetch_one('SELECT * FROM devices WHERE id=? AND revoked=0',(device_id,))
    if not row or not device: await ws.close(code=4403); return
    await ws.accept(); hub.devices[str(device_id)]=ws
    execute('UPDATE devices SET status=?,last_seen=? WHERE id=?',('ONLINE',now(),device_id)); log_event(device_id,'Device connected','WebSocket')
    await hub.broadcast({'type':'devices.updated'})
    try:
        while True:
            msg=json.loads(await ws.receive_text())
            if msg.get('type')=='heartbeat': execute('UPDATE devices SET last_seen=?,status=? WHERE id=?',(now(),'ONLINE',device_id))
            elif msg.get('type')=='device.info':
                execute('UPDATE devices SET model=?,manufacturer=?,android_version=?,agent_version=?,battery=?,network=?,ip=?,last_seen=? WHERE id=?',(msg.get('model',''),msg.get('manufacturer',''),msg.get('android_version',''),msg.get('agent_version',''),int(msg.get('battery',0)),msg.get('network',''),msg.get('ip',''),now(),device_id))
            elif msg.get('type')=='command.result':
                execute('UPDATE commands SET status=?,completed_at=?,response=? WHERE id=?',(msg.get('status','COMPLETED'),now(),json.dumps(msg.get('response',{})),int(msg.get('command_id')))); log_event(device_id,'Command completed',str(msg.get('command_id'))); await hub.broadcast({'type':'command.updated'})
            elif msg.get('type')=='notification':
                execute('INSERT INTO notifications(device_id,app,title,content) VALUES (?,?,?,?)',(device_id,msg.get('app',''),msg.get('title',''),msg.get('content',''))); await hub.broadcast({'type':'notification.new'})
    except WebSocketDisconnect: pass
    finally:
        hub.devices.pop(str(device_id),None); execute('UPDATE devices SET status=?,last_seen=? WHERE id=?',('OFFLINE',now(),device_id)); log_event(device_id,'Device disconnected','WebSocket'); await hub.broadcast({'type':'devices.updated'})
