import os, sys, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def ensure_dependencies():
    try:
        import fastapi, uvicorn, jinja2, multipart, itsdangerous  # noqa: F401
        return
    except Exception:
        req=ROOT/'requirements.txt'
        cmd=[sys.executable,'-m','pip','install','--user','-r',str(req)]
        print('Dependencies not present; trying automatic installation...')
        subprocess.check_call(cmd)

def main():
    os.environ.setdefault('HOST','0.0.0.0')
    os.environ.setdefault('PORT','80')
    ensure_dependencies()
    from app.database import init_db
    init_db()
    import uvicorn
    print('Android Admin starting on 0.0.0.0:80')
    print('Public URL is detected from X-Forwarded-Host/Proto or Host headers.')
    try:
        uvicorn.run('app.main:app', host='0.0.0.0', port=80, proxy_headers=True, forwarded_allow_ips='*')
    except PermissionError:
        print('ERROR: cannot bind 0.0.0.0:80. The hosting environment must permit the app to listen on port 80.')
        raise

if __name__=='__main__': main()
