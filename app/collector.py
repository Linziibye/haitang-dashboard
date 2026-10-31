import json
import os
import sys
import time
from pathlib import Path
from collections import Counter
from urllib.request import getproxies
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright
from .config import HOME, URL, setup
from . import database as db
from .parser import parse

class LoginRequired(Exception): pass

def progress(**fields):
    path=HOME/'data'/'sync-state.json'
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(fields,ensure_ascii=False),encoding='utf-8')
    os.replace(tmp,path)

def launch_context(p, visible=False):
    proxy=getproxies().get('https')
    return p.chromium.launch_persistent_context(str(HOME/'browser_profile'),headless=not visible,
        channel='chromium',proxy={'server':proxy} if proxy else None,
        viewport={'width':1280,'height':850},accept_downloads=False)

def get_page(page,url):
    for attempt in range(3):
        try:
            response=page.goto(url,wait_until='domcontentloaded',timeout=45000)
            page.wait_for_timeout(800)
            if 'login.php' in page.url or page.locator('input[type=password]').count(): raise LoginRequired()
            if page.locator('#mypages').count():
                from bs4 import BeautifulSoup
                source=BeautifulSoup(response.text(),'html.parser').select_one('#mypages')
                return str(source) if source else page.locator('#mypages').inner_html()
            raise RuntimeError('网站未返回稿费区域，请打开登录窗口检查验证码或网站状态。')
        except LoginRequired: raise
        except Exception:
            if attempt==2: raise
            time.sleep(2*(attempt+1))

def sync(full=False,visible=False):
    started=db.now(); pages=0; records=0
    with db.connect() as conn:
        ident=conn.execute('INSERT INTO syncs(started,status) VALUES (?,?)',(started,'running')).lastrowid
    progress(status='running',message='正在连接海棠…',pages=0,records=0)
    try:
        with sync_playwright() as p:
            ctx=launch_context(p,visible)
            try:
                page=ctx.pages[0] if ctx.pages else ctx.new_page()
                if visible:
                    page.goto(URL,wait_until='domcontentloaded',timeout=60000)
                    progress(status='login',message='请在海棠窗口自行登录，完成后会自动同步。',pages=0,records=0)
                    while True:
                        page.wait_for_timeout(1500)
                        if page.is_closed(): raise LoginRequired()
                        if 'login.php' not in page.url and not page.locator('input[type=password]').count():
                            if page.locator('#mypages').count() and ('稿費' in page.locator('#mypages').inner_text()): break
                    # Reload the read-only ledger, not whichever destination login selected.
                queue=[URL]; seen=set(); counts=Counter(); first_batch=None; newest_balance=None
                earliest=None; latest=None; observed=[]
                last=db.setting('last_success_time'); overlap_days=last[:10] if last and not full else None
                while queue:
                    url=queue.pop(0)
                    if url in seen: continue
                    html=get_page(page,url)
                    parsed=parse(html,url,db.setting('site_timezone','Asia/Shanghai'))
                    if parsed['pagination'] is None:
                        raise RuntimeError('未能识别网站分页，已停止以免误报完整采集。')
                    batch=parsed['records']
                    if not batch and pages==0:
                        # Empty ledger is accepted only when the actual table exists.
                        if '<table' not in html: raise RuntimeError('尚未识别到稿费表格，请先登录并检查网站。')
                    if pages==0:
                        first_batch=[r['fingerprint'] for r in batch]
                        newest_balance=parsed['balance']
                    pages+=1; seen.add(url); records+=len(batch)
                    for r in batch:
                        counts[r['fingerprint']]+=1
                        r['occurrence']=counts[r['fingerprint']]
                        # Raw canonical identity + multiplicity, not a lossy hash of rounded fields.
                        r['key']='id:'+r['source_id'] if r['source_id'] else r['fingerprint']+'#'+str(r['occurrence'])
                        earliest=min(earliest or r['time'],r['time']); latest=max(latest or r['time'],r['time'])
                        observed.append(r)
                    progress(status='running',message=f'已读取 {pages} 页 · {records} 条记录',pages=pages,records=records)
                    # A checkpoint retains already parsed rows; on restart rewalk the live top pages
                    # so changes to pagination cannot silently skip newer records.
                    db.set_setting('checkpoint',{'time':started,'pages':pages,'records':records,'last_url':url,'mode':'full' if full else 'incremental'})
                    if batch:
                        store(batch,started)
                    older=bool(batch and overlap_days and max(r['time'][:10] for r in batch)<overlap_days)
                    if older: break
                    for link in parsed['links']:
                        if link not in seen and link not in queue: queue.append(link)
                    if pages>100000: raise RuntimeError('分页异常，已停止。')
                    if queue: time.sleep(float(db.setting('request_delay',1.5)))
                # Recheck the newest page: if it moved during the scan, another pass is required.
                check=parse(get_page(page,URL),URL,db.setting('site_timezone','Asia/Shanghai'))
                if [r['fingerprint'] for r in check['records']]!=first_batch:
                    raise RuntimeError('采集期间出现新交易，已保存检查点；请再次刷新以核对分页衔接。')
                # Payment status can change independently of new income, so always refresh its pages.
                payment_url=URL+'&showmode=payment'; payment_counts=Counter(); payment_seen=set()
                while payment_url and payment_url not in payment_seen:
                    payment_seen.add(payment_url)
                    pay=parse(get_page(page,payment_url),payment_url,db.setting('site_timezone','Asia/Shanghai'))
                    for r in pay['records']:
                        payment_counts[r['fingerprint']]+=1; r['occurrence']=payment_counts[r['fingerprint']]
                        r['key']='id:'+r['source_id'] if r['source_id'] else r['fingerprint']+'#'+str(r['occurrence'])
                    store(pay['records'],started)
                    payment_url=pay['links'][0] if pay['links'] else None
                    if payment_url: time.sleep(float(db.setting('request_delay',1.5)))
                finished=db.now()
                db.set_setting('payments_checked',True)
                if check['balance'] is not None:
                    with db.connect() as conn: conn.execute('INSERT OR REPLACE INTO snapshots VALUES (?,?)',(finished,check['balance']))
                if earliest:
                    old=db.setting('coverage_start'); db.set_setting('coverage_start',min(old or earliest,earliest))
                # No unvisited pagination links means the ledger history exposed by the site was traversed.
                if not overlap_days: db.set_setting('complete_history',True)
                db.set_setting('last_success_time',finished); db.set_setting('checkpoint',None)
                with db.connect() as conn:
                    conn.execute('UPDATE syncs SET finished=?,status=?,pages=?,records=?,message=? WHERE id=?',
                        (finished,'success',pages,records,'同步完成',ident))
                db.backup()
                progress(status='success',message='同步完成',pages=pages,records=records,time=finished)
            finally: ctx.close()
    except Exception as exc:
        login=isinstance(exc,LoginRequired)
        # Exception strings may contain URLs; never log response headers or browser state.
        message='登录已失效，请打开登录窗口。' if login else str(exc).split('Call log:')[0][:240]
        with db.connect() as conn:
            conn.execute('UPDATE syncs SET finished=?,status=?,pages=?,records=?,message=? WHERE id=?',(db.now(),'login' if login else 'error',pages,records,message,ident))
        progress(status='login_required' if login else 'error',message=message,pages=pages,records=records)

def store(batch,stamp):
    cols=['key','source_id','fingerprint','occurrence','raw_time','time','kind','amount','raw_amount','nickname','work_id','work_name','chapter_id','chapter_name','status','detail','source_page']
    with db.connect() as conn:
        for r in batch:
            conn.execute(f"INSERT INTO transactions ({','.join(cols)},first_seen) VALUES ({','.join('?' for _ in cols)},?) ON CONFLICT(key) DO UPDATE SET status=excluded.status,detail=excluded.detail",[r[k] for k in cols]+[stamp])

if __name__=='__main__':
    setup(); db.init(); sync('--full' in sys.argv,'--login' in sys.argv)
