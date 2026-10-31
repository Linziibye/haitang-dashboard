import secrets
import sqlite3
import shutil
import threading
import os
from contextlib import closing
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from .config import ASSETS, HOME, TZ
from . import database as db
from .statistics import summary
from .exports import export
from .exchange_rates import refresh
from .browser import read_preference, save_preference, SystemBrowserError

def create_app(service):
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    token=secrets.token_urlsafe(32)
    @app.middleware('http')
    async def local_session(req,call_next):
        host=req.headers.get('host','')
        if not (host.startswith('127.0.0.1:') or host=='127.0.0.1' or host=='testserver'):
            return Response('Forbidden',status_code=403)
        origin=req.headers.get('origin')
        if origin and origin!=f'http://{host}': return Response('Forbidden',status_code=403)
        if req.url.path.startswith('/api/') and not secrets.compare_digest(req.headers.get('x-session',''),token):
            return Response('Forbidden',status_code=403)
        res=await call_next(req)
        res.headers['Cache-Control']='no-store'
        res.headers['X-Content-Type-Options']='nosniff'
        res.headers['Referrer-Policy']='no-referrer'
        res.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
        return res
    @app.get('/')
    def index(): return HTMLResponse((ASSETS/'index.html').read_text(encoding='utf-8').replace('__SESSION__',token))
    @app.get('/api/summary')
    def get_summary(start:str|None=None,end:str|None=None,work:str='all',nickname:str|None=None):
        try: return summary(start,end,work,nickname=nickname)
        except ValueError: raise HTTPException(400,'日期格式无效')
    @app.get('/api/status')
    def status(): return service.status()
    @app.post('/api/sync')
    def sync(full:bool=False,login:bool=False): return {'started':service.start_sync(full,login)}
    @app.get('/api/settings')
    def settings():
        return {'browser':read_preference(),'interval':db.setting('interval'),'site_timezone':db.setting('site_timezone'),'timezone_confirmed':db.setting('timezone_confirmed'),'data_dir':str(HOME),'backups':[p.name for p in sorted((HOME/'backups').glob('*.sqlite3'),reverse=True)],'checkpoint':db.setting('checkpoint')}
    @app.post('/api/settings')
    async def save_settings(req:Request):
        data=await req.json()
        if data.get('interval') not in (0,1,5,15,30): raise HTTPException(400,'同步间隔无效')
        if 'browser' in data:
            with service.lock:
                if service.busy() and data['browser'] != read_preference():
                    raise HTTPException(409,'请先等待同步或登录窗口结束，再切换采集浏览器。')
                try: save_preference(data['browser'])
                except SystemBrowserError as exc: raise HTTPException(400,str(exc))
        db.set_setting('interval',data['interval'])
        if 'timezone_confirmed' in data: db.set_setting('timezone_confirmed',bool(data['timezone_confirmed']))
        return {'ok':True}
    @app.post('/api/rate')
    def rate():
        threading.Thread(target=refresh,daemon=True).start(); return {'ok':True}
    @app.post('/api/clear-login')
    def clear_login():
        with service.lock:
            if service.busy(): raise HTTPException(409,'请先等待同步或登录窗口结束。')
            shutil.rmtree(HOME/'browser_profile'); (HOME/'browser_profile').mkdir()
        return {'ok':True}
    @app.get('/api/export')
    def download(start:str|None=None,end:str|None=None,work:str='all',currency:str='HTB',kind:str='xlsx',nickname:str|None=None):
        if kind not in ('xlsx','csv') or currency not in ('HTB','CNY'): raise HTTPException(400,'无效的导出格式')
        try: content=export(summary(start,end,work,nickname=nickname),currency,kind=='xlsx')
        except ValueError as e: raise HTTPException(400,str(e))
        filename=f'海棠稿费-{datetime.now(TZ):%Y%m%d-%H%M%S}.{kind}'
        (HOME/'exports'/filename).write_bytes(content)
        return Response(content,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if kind=='xlsx' else 'text/csv;charset=utf-8')
    @app.post('/api/chart-export/{name}')
    async def chart_export(name:str,req:Request):
        if name not in ('trend','readers','hours','daily','ranking'): raise HTTPException(400)
        content=await req.body()
        if len(content)>20*1024*1024 or not content.startswith(b'\x89PNG\r\n\x1a\n'): raise HTTPException(400,'图片无效')
        path=HOME/'exports'/f'{name}-{datetime.now(TZ):%Y%m%d-%H%M%S}.png'; path.write_bytes(content)
        return {'ok':True}
    @app.post('/api/open-exports')
    def open_exports():
        os.startfile(HOME/'exports'); return {'ok':True}
    @app.post('/api/backup')
    def backup():
        path=db.backup(True); return {'name':path.name}
    @app.get('/api/backup/{name}')
    def download_backup(name:str):
        if Path(name).name!=name or not name.endswith('.sqlite3'): raise HTTPException(400,'无效备份名')
        path=HOME/'backups'/name
        if not path.is_file(): raise HTTPException(404)
        return FileResponse(path,filename=name)
    @app.post('/api/restore')
    async def restore(req:Request):
        content=await req.body()
        if len(content)>200*1024*1024: raise HTTPException(400,'备份超过200MB')
        # Hold the sync lock across validation/replacement so no collector can start.
        with service.lock:
            if service.busy(): raise HTTPException(409,'请先等待同步结束。')
            tmp=HOME/'data'/'restore.tmp'
            try:
                tmp.write_bytes(content)
                with closing(sqlite3.connect(f'file:{tmp.as_posix()}?mode=ro',uri=True)) as source:
                    if source.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('数据库损坏')
                    tables={r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if not {'transactions','snapshots','settings','syncs','rates'}<=tables: raise ValueError('不是本应用的备份')
                    if source.execute('PRAGMA user_version').fetchone()[0]!=1: raise ValueError('数据库版本不兼容')
                    db.backup(True)
                    with db.connect() as target: source.backup(target)
                return {'ok':True}
            except (ValueError,sqlite3.Error) as e: raise HTTPException(400,str(e))
            finally: tmp.unlink(missing_ok=True)
    app.mount('/static',StaticFiles(directory=str(ASSETS)),name='static')
    return app
