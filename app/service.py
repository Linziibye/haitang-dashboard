import json
import os
import subprocess
import sys
import threading
import time
from .config import HOME, INSTALL
from . import database as db
from .exchange_rates import refresh

class Service:
    def __init__(self):
        self.process=None; self.lock=threading.RLock(); self.stop=threading.Event()
        self.last_started=0; self.rate_thread=None
    def start_sync(self,full=False,login=False):
        with self.lock:
            if self.stop.is_set(): return False
            if self.busy(): return False
            if getattr(sys,'frozen',False): cmd=[sys.executable,'--worker']
            else: cmd=[sys.executable,'-m','app.collector']
            if full: cmd.append('--full')
            if login: cmd.append('--login')
            state=HOME/'data'/'sync-state.json'
            state.write_text(json.dumps({'status':'running','message':'正在启动同步…','pages':0,'records':0}),encoding='utf-8')
            env=os.environ.copy(); env['PYTHONUTF8']='1'
            if hasattr(self,'log'): self.log.close()
            self.log=open(HOME/'logs'/'worker.log','w',encoding='utf-8')
            self.process=subprocess.Popen(cmd,cwd=str(INSTALL),env=env,stdout=self.log,stderr=self.log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            self.last_started=time.monotonic()
            return True
    def busy(self): return self.process is not None and self.process.poll() is None
    def status(self):
        with self.lock:
            try: state=json.loads((HOME/'data'/'sync-state.json').read_text(encoding='utf-8'))
            except (OSError,ValueError): state={'status':'idle','message':'等待同步','pages':0,'records':0}
            state['busy']=self.busy()
            if not state['busy'] and state['status'] in ('running','login'):
                state.update(status='error',message='上次同步已中断，点击刷新可从检查点重新核对。')
            state['rate_error']=db.setting('rate_error')
            return state
    def background(self):
        rate_checked=time.monotonic()
        self.rate_thread=threading.Thread(target=refresh,daemon=True); self.rate_thread.start()
        self.start_sync()
        while not self.stop.wait(2):
            if time.monotonic()-rate_checked>=12*3600:
                if not self.rate_thread.is_alive():
                    self.rate_thread=threading.Thread(target=refresh,daemon=True); self.rate_thread.start()
                    rate_checked=time.monotonic()
            interval=db.setting('interval',5)
            if interval and not self.busy() and time.monotonic()-self.last_started>=interval*60:
                # An expired login waits for the user instead of retrying every minute.
                if self.status()['status']!='login_required': self.start_sync()
    def close(self):
        self.stop.set()
        with self.lock:
            if self.busy():
                if os.name=='nt': subprocess.run(['taskkill','/PID',str(self.process.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                else: self.process.terminate()
                try: self.process.wait(timeout=10)
                except subprocess.TimeoutExpired: pass
            if hasattr(self,'log'): self.log.close()
