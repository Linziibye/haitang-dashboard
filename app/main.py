import ctypes
import os
import socket
import sys
import threading
import time
import logging
from .config import setup, HOME, INSTALL
from . import database as db

TITLE='海棠稿费看板'

def single_instance():
    if os.name!='nt': return None
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.restype=ctypes.c_void_p
    mutex=kernel.CreateMutexW(None,False,'Local\\HaitangDashboard-'+os.environ.get('USERNAME','user'))
    if ctypes.get_last_error()==183:
        user=ctypes.windll.user32
        for _ in range(30):
            hwnd=user.FindWindowW(None,TITLE)
            if hwnd:
                user.ShowWindow(hwnd,9 if user.IsIconic(hwnd) else 5); user.SetForegroundWindow(hwnd); break
            time.sleep(.2)
        kernel.CloseHandle(ctypes.c_void_p(mutex)); return False
    return mutex

def main():
    setup(); db.init()
    if '--worker' in sys.argv:
        from .collector import sync
        sync('--full' in sys.argv,'--login' in sys.argv); return
    mutex=single_instance()
    if mutex is False: return
    from .service import Service
    from .api import create_app
    import uvicorn
    service=Service(); app=create_app(service)
    sock=socket.socket(); sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    config=uvicorn.Config(app,host='127.0.0.1',port=port,log_level='warning',access_log=False,log_config=None)
    server=uvicorn.Server(config)
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True); thread.start()
    for _ in range(100):
        if server.started: break
        if not thread.is_alive(): raise RuntimeError('本地服务启动失败')
        time.sleep(.05)
    if not server.started: raise RuntimeError('本地服务未能及时启动')
    if '--serve' in sys.argv:
        print(f'http://127.0.0.1:{port}',flush=True)
        try:
            while thread.is_alive(): time.sleep(.5)
        except KeyboardInterrupt: pass
        finally: service.close(); server.should_exit=True; thread.join(5)
        return
    import webview
    webview.settings['ALLOW_DOWNLOADS']=True
    if os.name=='nt': ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('HaitangDashboard.Desktop')
    window=webview.create_window(TITLE,f'http://127.0.0.1:{port}',width=1440,height=980,min_size=(800,640),maximized=True,
        background_color='#f5f3f8',text_select=True)
    def closed():
        service.close(); server.should_exit=True
    window.events.closed+=closed
    window.events.shown+=lambda:window.maximize()
    started=threading.Event()
    def ready():
        if started.is_set(): return
        started.set()
        threading.Thread(target=service.background,daemon=True).start()
    window.events.loaded+=ready
    try:
        webview.start(gui='edgechromium',private_mode=True,icon=str(INSTALL/'app'/'frontend'/'icon.ico'))
    finally:
        closed(); thread.join(5); sock.close()
        if mutex: ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(mutex))

if __name__=='__main__': main()
