"""Parse only manuscript ledger content; never inspect login inputs."""
import re
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse, parse_qs
from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from .config import SCALE, SITE

TIME=re.compile(r'20\d{2}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?')

def amount(text):
    m=re.search(r'[-+]?\d[\d,]*(?:\.\d+)?',text.replace('−','-'))
    if not m: return None
    try: return int(Decimal(m[0].replace(',',''))*SCALE)
    except InvalidOperation: return None

def parse(html, url, timezone='Asia/Shanghai'):
    soup=BeautifulSoup(html,'html.parser')
    result=[]
    for tr in soup.select('tr'):
        cells=tr.find_all('td',recursive=False)
        if len(cells)<2: continue
        text=cells[0].get_text(' ',strip=True)
        tm=TIME.search(text)
        if not tm: continue
        money=cells[-1].get_text(' ',strip=True)
        units=amount(money)
        if units is None: continue
        rawtime=tm[0].replace('/','-')
        dt=datetime.fromisoformat(rawtime).replace(tzinfo=ZoneInfo(timezone)).astimezone(ZoneInfo('Asia/Shanghai'))
        kind='income' if re.search(r'稿[費费][報报]酬|稿[費费]收入',text) else ('withdrawal' if re.search(r'[請请]款|提[現现]|匯款',text) else 'adjustment')
        nick=''
        for el in cells[0].select('a, font'):
            color=(el.get('color','')+' '+el.get('style','')).lower()
            if 'green' in color or '#008000' in color or '#00aa00' in color:
                nick=el.get_text(' ',strip=True); break
        detail=re.sub(r'^.*?稿[費费][報报]酬\s*','',text) if kind=='income' else text
        wm=re.search(r'(?:訂閱|订阅|打賞|打赏)\s*[:：]\s*(.*?)(?:\s*章[節节]\s*[:：]|$)',detail)
        cm=re.search(r'章[節节]\s*[:：]\s*(.*)',detail)
        work=wm[1].strip() if wm else ''
        chapter=cm[1].strip() if cm else ''
        if not nick and wm:
            nick=re.split(r'訂閱|订阅|打賞|打赏',detail)[0].strip()
        wid=cid=sid=''
        for a in cells[0].select('a[href]'):
            q=parse_qs(urlparse(urljoin(url,a['href'])).query)
            wid=wid or next((q[k][0] for k in ('bookid','book_id','bid') if k in q),'')
            cid=cid or next((q[k][0] for k in ('chapterid','chapter_id','cid') if k in q),'')
            sid=sid or next((q[k][0] for k in ('recordid','feeid','transactionid') if k in q),'')
        if not wid and work: wid='name:'+work
        status='unknown'
        if kind=='withdrawal':
            if re.search(r'失敗|失败|撤[銷销]|取消|退回',text): status='invalid'
            elif re.search(r'完成|成功|已[匯汇]|已[付支]',text): status='valid'
            elif re.search(r'待|處理|处理|申[請请]',text): status='pending'
        identity=[rawtime,kind,money] if kind=='withdrawal' else [rawtime,kind,money,nick,wid,cid,chapter,detail]
        fp=json.dumps(identity,ensure_ascii=False,separators=(',',':'))
        result.append(dict(source_id=sid,fingerprint=fp,raw_time=rawtime,time=dt.isoformat(),kind=kind,amount=units,
            raw_amount=money,nickname=nick or '没有名字',work_id=wid or 'unknown',work_name=work or '未识别作品',
            chapter_id=cid,chapter_name=chapter,status=status,detail=detail,source_page=url))
    # Pagination links are restricted to the ledger action on the same origin.
    links=[]
    current_mode=parse_qs(urlparse(url).query).get('showmode',[''])[0]
    for a in soup.select('a[href]'):
        target=urljoin(url,a['href']); u=urlparse(target); q=parse_qs(u.query)
        if u.netloc==urlparse(SITE).netloc and q.get('act')==['manuscriptfeelist'] and q.get('showmode',[''])[0]==current_mode:
            if target!=url and target not in links: links.append(target)
    text=soup.get_text(' ',strip=True)
    pagination=re.search(r'所在[頁页][數数]\s*[:：]\s*(\d+)\s*/\s*(\d+)',text)
    if pagination:
        current,total=map(int,pagination.groups())
        links=[SITE+f'/?act=manuscriptfeelist&showmode={current_mode}&pages={current+1}'] if current<total else []
    balance=None
    bm=re.search(r'(?:稿[費费](?:總|总)?(?:[餘余][額额]|[結结][餘余])|[目當当]前[餘余][額额]|[餘余][額额])\s*[:：]?\s*(?:NT\$|\$)?\s*([\d,]+(?:\.\d+)?)',text)
    if bm: balance=amount(bm[1])
    return {'records':result,'links':links,'balance':balance,'text':text,'pagination':pagination.groups() if pagination else None}
