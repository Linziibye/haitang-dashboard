from collections import defaultdict
from datetime import datetime, timedelta, date
from decimal import Decimal
from .config import TZ, SCALE
from . import database as db

def value(n): return float(Decimal(str(n))/SCALE)

def days(a,b):
    return [a+timedelta(days=i) for i in range(max(0,(b-a).days+1))]

def growth(current, previous):
    if previous==0: return '新增收入' if current else '—'
    return f'{(current-previous)/abs(previous)*100:+.1f}%'

def summary(start=None,end=None,work='all',clock=None,nickname=None):
    current=clock or datetime.now(TZ)
    sync=db.rows("SELECT * FROM syncs WHERE status='success' ORDER BY id DESC LIMIT 1")
    cutoff=datetime.fromisoformat(sync[0]['finished']) if sync else current
    today=current.date(); yesterday=today-timedelta(days=1)
    records=db.rows('SELECT * FROM transactions ORDER BY time,key')
    incomes=[r for r in records if r['kind']=='income']
    coverage=db.setting('coverage_start')
    first=date.fromisoformat(coverage[:10]) if coverage else (date.fromisoformat(incomes[0]['time'][:10]) if incomes else today)
    a=max(date.fromisoformat(start) if start else today-timedelta(days=29),first)
    b=min(date.fromisoformat(end) if end else today,today)
    filtered=[r for r in incomes if (work=='all' or r['work_id']==work)]
    selected=[r for r in filtered if a.isoformat()<=r['time'][:10]<=b.isoformat() and (not nickname or r['nickname']==nickname)]
    daily=defaultdict(lambda: [0,0])
    for r in filtered:
        daily[r['time'][:10]][0]+=r['amount']; daily[r['time'][:10]][1]+=1
    def total(lo,hi): return sum(v[0] for k,v in daily.items() if lo.isoformat()<=k<=hi.isoformat())
    def today_to_at(d, t):
        return sum(r['amount'] for r in filtered if r['time'][:10]==d.isoformat() and datetime.fromisoformat(r['time']).timetz().replace(tzinfo=None)<=t)
    # A stale snapshot does not pretend that yesterday's data is today's income.
    if cutoff.date()==today:
        t=cutoff.timetz().replace(tzinfo=None)
        same=today_to_at(yesterday,t); td=today_to_at(today,t)
    else: same=td=0
    complete_count=max(0,(today-first).days)
    recent_days=min(7,complete_count)
    week=total(max(first,today-timedelta(days=7)),yesterday)
    prevweek=total(today-timedelta(days=14),today-timedelta(days=8))
    snapshots=db.rows('SELECT * FROM snapshots ORDER BY time')
    withdrawals=[r for r in records if r['kind']=='withdrawal']
    confirmed=[r for r in withdrawals if r['status']=='valid']
    pending=[r for r in withdrawals if r['status'] in ('unknown','pending')]
    core={'balance':value(snapshots[-1]['amount']) if snapshots else None,
          'withdrawn':value(sum(abs(r['amount']) for r in confirmed)) if withdrawals or db.setting('payments_checked',False) else None,
          'withdrawal_unconfirmed':len(pending),'total':value(sum(r['amount'] for r in incomes)),
          'today':value(sum(r['amount'] for r in incomes if r['time'][:10]==today.isoformat() and datetime.fromisoformat(r['time'])<=cutoff))}
    core['reconciliation_difference']=value(sum(r['amount'] for r in records if r['kind']!='withdrawal' or r['status']=='valid')-snapshots[-1]['amount']) if snapshots else None
    amount=sum(r['amount'] for r in selected)
    bynick=defaultdict(lambda: [0,0]); bywork=defaultdict(lambda:[0,0,'']); bych=defaultdict(lambda:[0,0,''])
    for r in selected:
        bynick[r['nickname']][0]+=r['amount']; bynick[r['nickname']][1]+=1
        w=bywork[r['work_id']]; w[0]+=r['amount']; w[1]+=1; w[2]=r['work_name']
        if r['chapter_name']:
            c=bych[r['chapter_id'] or r['chapter_name']]; c[0]+=r['amount']; c[1]+=1; c[2]=r['chapter_name']
    ndays=len(days(a,min(b,yesterday)))
    hour_income=[0]*24; hour_count=[0]*24
    only_today=a==b==today
    for r in selected:
        when=datetime.fromisoformat(r['time'])
        if when.date()==today and not only_today: continue
        if only_today and when>cutoff: continue
        hour_income[when.hour]+=r['amount']; hour_count[when.hour]+=1
    dayseries=[]
    for d in days(a,b):
        v=daily[d.isoformat()]
        ma=None
        if d<today and d-timedelta(days=6)>=first:
            ma=value(total(d-timedelta(days=6),d))/7
        macount=None
        if d<today and d-timedelta(days=6)>=first:
            macount=sum(daily[(d-timedelta(days=i)).isoformat()][1] for i in range(7))/7
        dayseries.append({'date':d.isoformat(),'amount':value(v[0]),'count':v[1],'average':value(v[0])/v[1] if v[1] else 0,'ma':ma,'ma_count':macount,'unfinished':d==today})
    nicklist=sorted([{'name':k,'amount':value(v[0]),'count':v[1],'share':v[0]/amount if amount else 0} for k,v in bynick.items()],key=lambda x:x['amount'],reverse=True)
    def ranking(source,chapter=False):
        complete=defaultdict(int)
        for r in selected:
            if r['time'][:10]<today.isoformat(): complete[(r['chapter_id'] or r['chapter_name']) if chapter else r['work_id']]+=r['amount']
        return sorted([{'id':k,'name':v[2],'amount':value(v[0]),'count':v[1],'average':value(complete[k])/ndays if ndays else None,'share':v[0]/amount if amount else 0} for k,v in source.items()],key=lambda x:x['amount'],reverse=True)
    highest=max(dayseries,key=lambda x:x['amount']) if dayseries else None
    metrics={'average':value(total(first,yesterday))/complete_count if complete_count else None,
        'recent_average':value(week)/recent_days if recent_days else None,'recent_days':recent_days,
        'week_growth':growth(week,prevweek) if complete_count>=14 else '数据不足',
        'same_growth':growth(td,same) if cutoff.date()==today and yesterday>=first else '数据不足',
        'today':value(td),'yesterday':value(total(yesterday,yesterday)),
        'month':value(total(max(first,today.replace(day=1)),today)),
        'selected':value(amount),'count':len(selected),'per_transaction':value(amount)/len(selected) if selected else None,
        'active':len(nicklist),'top10_share':sum(n['share'] for n in nicklist[:10]),'highest':highest}
    works={r['work_id']:r['work_name'] for r in incomes}
    rates=db.rows('SELECT * FROM rates ORDER BY fetched DESC LIMIT 1')
    movements=[r for r in records if (r['kind']!='withdrawal' or r['status']=='valid') and datetime.fromisoformat(r['time'])<=cutoff]
    # A complete ledger reconciled against the site's balance supports a historical curve.
    # Retain the observed snapshot separately; do not rewrite a transaction to eliminate rounding.
    balance_opening=None
    if snapshots and db.setting('complete_history',False) and not pending:
        anchor=snapshots[-1]
        opening=anchor['amount']-sum(r['amount'] for r in movements if r['time']<=anchor['time'])
        if abs(opening)<=10000: balance_opening=0
    return {'core':core,'metrics':metrics,'works':[{'id':k,'name':v} for k,v in works.items()],
        'cumulative_before':value(sum(r['amount'] for r in filtered if r['time'][:10]<a.isoformat())),
        'balance_opening':balance_opening,
        'balance_before':(balance_opening+value(sum(r['amount'] for r in movements if r['time'][:10]<a.isoformat()))) if balance_opening is not None else None,
        'balance_history':[{'time':r['time'],'amount':value(r['amount']),'kind':r['kind']} for r in movements if a.isoformat()<=r['time'][:10]<=b.isoformat()],
        'range':{'start':a.isoformat(),'end':b.isoformat(),'complete_days':ndays},'coverage_start':first.isoformat() if incomes else None,
        'complete_history':db.setting('complete_history',False),'cutoff':cutoff.isoformat() if sync else None,
        'daily':dayseries,'readers':nicklist,'ranking':ranking(bywork),'chapters':ranking(bych,True),
        'hours':[{'hour':h,'amount':value(hour_income[h]),'count':hour_count[h],
                  'mean_amount':value(hour_income[h])/ndays if ndays else None,
                  'mean_count':hour_count[h]/ndays if ndays else None,
                  'future':only_today and (cutoff.date()!=today or h>cutoff.hour),
                  'unfinished':only_today and h==cutoff.hour} for h in range(24)],'only_today':only_today,
        'snapshots':[{'time':r['time'],'amount':value(r['amount'])} for r in snapshots if a.isoformat()<=r['time'][:10]<=b.isoformat()],
        'withdrawals':[{**r,'amount':value(r['amount'])} for r in withdrawals],
        'transactions':[{**r,'amount':value(r['amount'])} for r in reversed(selected)],
        'rate':rates[0] if rates else None,'timezone_confirmed':db.setting('timezone_confirmed',False)}
