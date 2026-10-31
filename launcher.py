from app.main import main
if __name__=='__main__':
    try:
        main()
    except Exception:
        import traceback
        from app.config import HOME, setup
        setup()
        (HOME/'logs'/'startup.log').write_text(traceback.format_exc(),encoding='utf-8')
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,'启动失败。请查看本机数据目录 logs\\startup.log，或将日志提供给开发者。','海棠稿费看板',16)
