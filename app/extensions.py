import hashlib
import secrets
import shutil
import time
from fastapi import HTTPException, Request
from app.main import app, authed, db, public_base_url, log_event

@app.post('/api/device/enroll')
async def device_enroll(payload: dict):
    code = str(payload.get('code','')).strip()
    if not code: raise HTTPException(400, 'Código de inscrição obrigatório')
    with db() as c:
        req = c.execute('SELECT * FROM enrollment_requests WHERE code=? AND used=0 AND expires_at>?',(code,time.time())).fetchone()
        if not req: raise HTTPException(400, 'Código inválido ou expirado')
        device_id = 'dev-' + secrets.token_hex(8)
        token = secrets.token_urlsafe(32)
        c.execute('UPDATE enrollment_requests SET used=1 WHERE code=?',(code,))
        c.execute('INSERT INTO devices(id,name,model,manufacturer,android_version,agent_version,battery,status,enrolled_at) VALUES(?,?,?,?,?,?,?,?,?)',(device_id,payload.get('name',device_id),payload.get('model',''),payload.get('manufacturer',''),payload.get('android_version',''),payload.get('agent_version','1.0.0'),payload.get('battery',100),'OFFLINE',time.time()))
        c.execute('INSERT INTO device_tokens(device_id,token_hash,created_at) VALUES(?,?,?)',(device_id,hashlib.sha256(token.encode()).hexdigest(),time.time()))
    log_event(device_id,'enrollment','Enrollment completed')
    return {'device_id':device_id,'token':token,'server_url':public_base_url()}

@app.post('/api/apk/build')
async def apk_build(request: Request):
    if not authed(request): raise HTTPException(401)
    started=time.time(); url=public_base_url(request)
    java=shutil.which('java'); gradle=shutil.which('gradle')
    status='BUILD TOOLCHAIN UNAVAILABLE'
    error='Java/Gradle não disponíveis no ambiente de hospedagem.' if not (java and gradle) else 'Toolchain encontrada; build automático requer Android SDK e wrapper configurado.'
    with db() as c: c.execute('INSERT INTO apk_builds(version,status,public_url,started_at,finished_at,error) VALUES(?,?,?,?,?,?)',('1.0.0',status,url,started,time.time(),error))
    return {'status':status,'public_url':url,'error':error}
