import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
ASSETS = BASE / 'app' / 'frontend'
INSTALL = Path(sys.executable).parent if getattr(sys, 'frozen', False) else BASE
HOME = Path(os.environ.get('HAITANG_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'HaitangDashboard')))
SITE = 'https://www.lvhtebook.com'
URL = SITE + '/?act=manuscriptfeelist'
SCALE = 100000000

def setup():
    for name in ('data','browser_profile','backups','exports','logs'):
        (HOME/name).mkdir(parents=True, exist_ok=True)
