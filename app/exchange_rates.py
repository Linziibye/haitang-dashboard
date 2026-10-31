from datetime import datetime,timedelta
from decimal import Decimal
from urllib.request import getproxies
import httpx
from . import database as db
from .config import TZ

SOURCE='https://www.floatrates.com/daily/twd.json'

def refresh():
    cached=db.rows('SELECT * FROM rates ORDER BY fetched DESC LIMIT 1')
    if cached and datetime.now(TZ)-datetime.fromisoformat(cached[0]['fetched'])<timedelta(hours=12): return
    try:
        proxy=getproxies().get('https')
        with httpx.Client(proxy=proxy,timeout=20,follow_redirects=True) as client:
            res=client.get(SOURCE); res.raise_for_status(); item=res.json()['cny']
        rate=Decimal(str(item['rate']))
        if not rate.is_finite() or rate<=0: raise ValueError('invalid rate')
        with db.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO rates VALUES (?,?,?,?)',(item['date'],str(rate),'FloatRates · TWD/CNY',db.now()))
        db.set_setting('rate_error',None)
    except Exception:
        db.set_setting('rate_error','汇率获取失败，使用最近成功参考汇率。' if cached else '人民币换算暂不可用，请稍后重试。')
