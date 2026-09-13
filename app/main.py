from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import uvicorn

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB = DATA / "platform.db"
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
PORT = 80
HOST = "0.0.0.0"
APP_VERSION = "1.0.0"

DATA.mkdir(exist_ok=True)
STATIC.mkdir(exist_ok=True)

app = FastAPI(title="Admistracao GPT", version=APP_VERSION)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "change-me-in-production"), same_site="lax")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES))

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

browser_clients: set[WebSocket] = set()
device_clients: dict[str, WebSocket] = {}


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT NOT NULL, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, name TEXT NOT NULL, model TEXT, manufacturer TEXT, android_version TEXT, agent_version TEXT,
            battery INTEGER DEFAULT 100, status TEXT DEFAULT 'OFFLINE', network TEXT, ip TEXT, last_seen REAL, enrolled_at REAL NOT NULL, demo INTEGER DEFAULT 0, revoked INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS device_tokens (device_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, created_at REAL NOT NULL, revoked INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS enrollment_requests (code TEXT PRIMARY KEY, created_at REAL NOT NULL, expires_at REAL NOT NULL, used INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS commands (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, type TEXT, payload TEXT, status TEXT, created_at REAL, sent_at REAL, completed_at REAL, response TEXT);
        CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, content TEXT, status TEXT, created_at REAL);
        CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, app TEXT, title TEXT, content TEXT, created_at REAL);
        CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, kind TEXT, message TEXT, status TEXT, created_at REAL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS apk_builds (id INTEGER PRIMARY KEY AUTOINCREMENT, version TEXT, status TEXT, public_url TEXT, started_at REAL, finished_at REAL, error TEXT, path TEXT);
        """)
        row = c.execute("SELECT id FROM users WHERE username=?", (ADMIN_USER,)).fetchone()
        if not row:
            c.execute("INSERT INTO users(username,password_hash,created_at) VALUES(?,?,?)", (ADMIN_USER, hash_password(ADMIN_PASSWORD), time.time()))
        for k, v in {"platform_name":"Android Control Center", "version":APP_VERSION}.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k,v))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt, digest = encoded.split(":", 1)
        expected = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
        return hmac.compare_digest(expected, digest)
    except Exception:
        return False


def public_base_url(request: Request | None = None) -> str | None:
    env = os.getenv("PUBLIC_BASE_URL")
    if env:
        return env.rstrip("/")
    if request is None:
        return None
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not forwarded_host:
        return None
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{proto}://{forwarded_host}".rstrip("/")


def authed(request: Request) -> bool:
    return bool(request.session.get("admin"))


def log_event(device_id: str | None, kind: str, message: str, status: str = "INFO"):
    with db() as c:
        c.execute("INSERT INTO logs(device_id,kind,message,status,created_at) VALUES(?,?,?,?,?)", (device_id, kind, message, status, time.time()))


async def broadcast(event: dict):
    dead = []
    for ws in browser_clients:
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        browser_clients.discard(ws)


def seed_demo():
    demo = [("demo-001","Pixel Demo","Google","Pixel 8","14",92,"Wi-Fi","10.0.0.21"),("demo-002","Samsung Demo","Samsung","Galaxy S24","14",61,"5G","10.0.0.22"),("demo-003","Offline Demo","Motorola","Edge 40","13",38,"Offline","")]
    with db() as c:
        for did,name,mfr,model,android,battery,network,ip in demo:
            c.execute("INSERT OR IGNORE INTO devices(id,name,manufacturer,model,android_version,agent_version,battery,status,network,ip,last_seen,enrolled_at,demo) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)",
                      (did,name,mfr,model,android,"1.0.0",battery,"OFFLINE" if did.endswith("003") else "ONLINE",network,ip,time.time(),time.time()))


@app.on_event("startup")
async def startup():
    init_db()
    seed_demo()


@app.get("/health")
async def health():
    try:
        with db() as c: c.execute("SELECT 1")
        return {"status":"ok","database":"ok","websocket":"ready","port":PORT,"version":APP_VERSION}
    except Exception as e:
        return JSONResponse({"status":"degraded","error":str(e)}, status_code=503)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return RedirectResponse("/dashboard" if authed(request) else "/login")


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request":request})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    with db() as c: row = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return templates.TemplateResponse("login.html", {"request":request,"error":"Credenciais inválidas"}, status_code=401)
    request.session["admin"] = username
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not authed(request): return RedirectResponse("/login")
    with db() as c:
        total = c.execute("SELECT count(*) n FROM devices WHERE revoked=0").fetchone()["n"]
        online = c.execute("SELECT count(*) n FROM devices WHERE status='ONLINE' AND revoked=0").fetchone()["n"]
        commands = c.execute("SELECT count(*) n FROM commands").fetchone()["n"]
        logs = c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 8").fetchall()
    return templates.TemplateResponse("dashboard.html", {"request":request,"total":total,"online":online,"offline":total-online,"commands":commands,"logs":logs,"public_url":public_base_url(request)})


@app.get("/devices", response_class=HTMLResponse)
async def devices(request: Request):
    if not authed(request): return RedirectResponse("/login")
    with db() as c: rows = c.execute("SELECT * FROM devices WHERE revoked=0 ORDER BY enrolled_at DESC").fetchall()
    return templates.TemplateResponse("devices.html", {"request":request,"devices":rows})


@app.get("/device/{device_id}", response_class=HTMLResponse)
async def device_page(request: Request, device_id: str):
    if not authed(request): return RedirectResponse("/login")
    with db() as c:
        d = c.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        logs = c.execute("SELECT * FROM logs WHERE device_id=? ORDER BY id DESC LIMIT 30", (device_id,)).fetchall()
        messages = c.execute("SELECT * FROM messages WHERE device_id=? ORDER BY id DESC LIMIT 30", (device_id,)).fetchall()
    if not d: raise HTTPException(404, "Dispositivo não encontrado")
    return templates.TemplateResponse("device.html", {"request":request,"device":d,"logs":logs,"messages":messages})


@app.get("/apk-builder", response_class=HTMLResponse)
async def apk_builder(request: Request):
    if not authed(request): return RedirectResponse("/login")
    return templates.TemplateResponse("apk_builder.html", {"request":request,"public_url":public_base_url(request)})


@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    if not authed(request): return RedirectResponse("/login")
    with db() as c: rows = c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 200").fetchall()
    return templates.TemplateResponse("logs.html", {"request":request,"logs":rows})


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    if not authed(request): return RedirectResponse("/login")
    with db() as c: rows = c.execute("SELECT key,value FROM settings ORDER BY key").fetchall()
    return templates.TemplateResponse("settings.html", {"request":request,"settings":rows,"public_url":public_base_url(request),"version":APP_VERSION})


@app.get("/api/summary")
async def api_summary(request: Request):
    if not authed(request): raise HTTPException(401)
    with db() as c:
        total = c.execute("SELECT count(*) n FROM devices WHERE revoked=0").fetchone()["n"]
        online = c.execute("SELECT count(*) n FROM devices WHERE status='ONLINE' AND revoked=0").fetchone()["n"]
        return {"total":total,"online":online,"offline":total-online,"commands":c.execute("SELECT count(*) n FROM commands").fetchone()["n"]}


@app.post("/api/enroll")
async def api_enroll(request: Request):
    if not authed(request): raise HTTPException(401)
    code = f"{secrets.randbelow(1000000):06d}"
    with db() as c: c.execute("INSERT INTO enrollment_requests(code,created_at,expires_at) VALUES(?,?,?)", (code,time.time(),time.time()+900))
    return {"code":code,"expires_in":900}


@app.post("/api/devices/{device_id}/command")
async def send_command(request: Request, device_id: str):
    if not authed(request): raise HTTPException(401)
    payload = await request.json()
    typ = payload.get("type")
    if typ not in {"PING","LOCK","SHOW_MESSAGE","START_SCREEN","STOP_SCREEN"}:
        raise HTTPException(400,"Comando não permitido")
    with db() as c:
        c.execute("INSERT INTO commands(device_id,type,payload,status,created_at) VALUES(?,?,?,?,?)", (device_id,typ,json.dumps(payload),"PENDING",time.time()))
        cid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    if device_id in device_clients:
        try:
            await device_clients[device_id].send_json({"type":"command","id":cid,"command":typ,"payload":payload})
            with db() as c: c.execute("UPDATE commands SET status='SENT',sent_at=? WHERE id=?", (time.time(),cid))
        except Exception:
            pass
    log_event(device_id,"command",f"Command {typ} queued")
    await broadcast({"event":"command","device_id":device_id,"type":typ})
    return {"id":cid,"status":"SENT" if device_id in device_clients else "PENDING"}


@app.post("/api/devices/{device_id}/message")
async def send_message(request: Request, device_id: str):
    if not authed(request): raise HTTPException(401)
    body = await request.json(); content = str(body.get("content","")).strip()
    if not content: raise HTTPException(400,"Mensagem vazia")
    with db() as c: c.execute("INSERT INTO messages(device_id,content,status,created_at) VALUES(?,?,?,?)",(device_id,content,"PENDING",time.time()))
    await broadcast({"event":"message","device_id":device_id,"content":content})
    if device_id in device_clients:
        await device_clients[device_id].send_json({"type":"message","content":content})
    return {"status":"SENT" if device_id in device_clients else "PENDING"}


@app.websocket("/ws/browser")
async def browser_ws(ws: WebSocket):
    await ws.accept(); browser_clients.add(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect:
        browser_clients.discard(ws)


@app.websocket("/ws/device/{device_id}")
async def device_ws(ws: WebSocket, device_id: str):
    token = ws.query_params.get("token","")
    with db() as c: row = c.execute("SELECT token_hash,revoked FROM device_tokens WHERE device_id=?",(device_id,)).fetchone()
    if not row or row["revoked"] or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), row["token_hash"]):
        await ws.close(code=1008); return
    await ws.accept(); device_clients[device_id] = ws
    with db() as c: c.execute("UPDATE devices SET status='ONLINE',last_seen=? WHERE id=?",(time.time(),device_id))
    log_event(device_id,"connect","Device connected")
    await broadcast({"event":"device_status","device_id":device_id,"status":"ONLINE"})
    try:
        while True:
            data = await ws.receive_json()
            kind = data.get("type")
            with db() as c: c.execute("UPDATE devices SET last_seen=?,battery=?,ip=?,network=? WHERE id=?",(time.time(),data.get("battery",100),data.get("ip",""),data.get("network",""),device_id))
            if kind == "command_result":
                with db() as c: c.execute("UPDATE commands SET status=?,completed_at=?,response=? WHERE id=?",(data.get("status","COMPLETED"),time.time(),json.dumps(data.get("response")),data.get("id")))
            elif kind == "notification":
                with db() as c: c.execute("INSERT INTO notifications(device_id,app,title,content,created_at) VALUES(?,?,?,?,?)",(device_id,data.get("app",""),data.get("title",""),data.get("content",""),time.time()))
            await broadcast({"event":kind,"device_id":device_id,"data":data})
    except WebSocketDisconnect:
        if device_clients.get(device_id) is ws: device_clients.pop(device_id,None)
        with db() as c: c.execute("UPDATE devices SET status='OFFLINE',last_seen=? WHERE id=?",(time.time(),device_id))
        log_event(device_id,"disconnect","Device disconnected")
        await broadcast({"event":"device_status","device_id":device_id,"status":"OFFLINE"})


def bootstrap():
    init_db()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
