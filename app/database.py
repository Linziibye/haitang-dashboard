import json
import sqlite3
import threading
from contextlib import contextmanager, closing
from datetime import datetime
from .config import HOME, TZ
LOCK=threading.RLock()

def now():
    return datetime.now(TZ).isoformat(timespec='seconds')

@contextmanager
def connect():
    with LOCK:
        db = sqlite3.connect(HOME/'data'/'haitang.sqlite3', timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

def init():
    with connect() as conn:
        version=conn.execute('PRAGMA user_version').fetchone()[0]
        existing=conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    if version>1: raise RuntimeError('数据库版本高于本程序支持版本，请使用对应新版程序。')
    if existing and version<1: backup(True)
    with connect() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS transactions(
          key TEXT PRIMARY KEY, source_id TEXT, fingerprint TEXT NOT NULL, occurrence INTEGER NOT NULL,
          raw_time TEXT NOT NULL, time TEXT NOT NULL, kind TEXT NOT NULL, amount INTEGER NOT NULL,
          raw_amount TEXT NOT NULL, nickname TEXT NOT NULL, work_id TEXT NOT NULL, work_name TEXT NOT NULL,
          chapter_id TEXT NOT NULL, chapter_name TEXT NOT NULL, status TEXT NOT NULL,
          detail TEXT NOT NULL, first_seen TEXT NOT NULL, source_page TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS tx_time ON transactions(time);
        CREATE TABLE IF NOT EXISTS snapshots(time TEXT PRIMARY KEY, amount INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS syncs(id INTEGER PRIMARY KEY, started TEXT, finished TEXT, status TEXT,
          pages INTEGER DEFAULT 0, records INTEGER DEFAULT 0, message TEXT);
        CREATE TABLE IF NOT EXISTS rates(time TEXT PRIMARY KEY, rate TEXT, source TEXT, fetched TEXT);
        PRAGMA user_version=1;
        ''')
    defaults={'interval':5,'request_delay':1.5,'coverage_start':None,'complete_history':False,'site_timezone':'Asia/Shanghai','timezone_confirmed':False}
    for k,v in defaults.items():
        if setting(k, '__missing__') == '__missing__': set_setting(k,v)

def setting(k, default=None):
    with connect() as db:
        row=db.execute('SELECT value FROM settings WHERE key=?',(k,)).fetchone()
    return json.loads(row[0]) if row else default

def set_setting(k,v):
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(k,json.dumps(v,ensure_ascii=False)))

def rows(sql, params=()):
    with connect() as db: return [dict(r) for r in db.execute(sql,params)]

def backup(force=False):
    day=datetime.now(TZ).date().isoformat()
    existing=list((HOME/'backups').glob(day+'-*.sqlite3'))
    if existing and not force: return existing[-1]
    path=HOME/'backups'/f'{day}-{datetime.now(TZ):%H%M%S%f}.sqlite3'
    with connect() as src, closing(sqlite3.connect(path)) as dst: src.backup(dst)
    files=sorted((HOME/'backups').glob('*.sqlite3'))
    for old in files[:-30]: old.unlink()
    return path

