#!/usr/bin/env python3
import base64, csv, hashlib, hmac, io, json, os, secrets, sqlite3, threading, time, urllib.request, urllib.parse
from datetime import timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from core import *
from adapter import normalize, load_config
from metro_web import parse_page, URL as METRO_WEB_URL
ROOT=Path(__file__).parent
DATA=Path(os.getenv('TRACKER_DATA',str(ROOT/'data')));DATA.mkdir(exist_ok=True,parents=True)
DB=DATA/'tracker.sqlite3'
PUBLIC_URL='https://tcgmetro.blob.core.windows.net/stationnames/stations.json'
LOCK=threading.Lock()
POLL_LOCK=threading.Lock()

def conn():
    c=sqlite3.connect(DB,timeout=30);c.row_factory=sqlite3.Row;return c

def init():
    with conn() as c:
        c.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS records(id INTEGER PRIMARY KEY, car INTEGER, pair INTEGER, time TEXT, kind TEXT, run TEXT, station TEXT, destination TEXT, note TEXT, source TEXT, photo TEXT DEFAULT '', origin TEXT DEFAULT 'manual', UNIQUE(car,time,kind,run,station,origin));
        CREATE TABLE IF NOT EXISTS engineering(id INTEGER PRIMARY KEY,pair INTEGER,start TEXT,state TEXT,note TEXT,source TEXT,created TEXT);
        CREATE TABLE IF NOT EXISTS coverage(day TEXT PRIMARY KEY,value REAL,note TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS polls(id INTEGER PRIMARY KEY,time TEXT,kind TEXT,status TEXT,message TEXT);
        CREATE TABLE IF NOT EXISTS live(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,time TEXT,action TEXT,detail TEXT);
        ''')
        for k,v in DEFAULTS.items():c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',(k,json.dumps(v)))
        c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',('created',json.dumps(now().isoformat())))
    key=DATA/'access-key.txt'
    if not key.exists():
        key.write_text(secrets.token_urlsafe(24));os.chmod(key,0o600)
    return key.read_text().strip()
KEY=init()

def settings():
    with conn() as c:return {r['key']:json.loads(r['value']) for r in c.execute('SELECT * FROM settings')}

def audit(c,action,detail):c.execute('INSERT INTO audit(time,action,detail) VALUES(?,?,?)',(now().isoformat(),action,json.dumps(detail,ensure_ascii=False)))

def getrows(table):
    with conn() as c:return [dict(r) for r in c.execute('SELECT * FROM '+table+' ORDER BY id')]

def save_record(d,origin='manual',photo=''):
    v=validate_record(d)
    if photo:
        if not photo.startswith(('data:image/jpeg;base64,','data:image/png;base64,','data:image/webp;base64,')):raise ValueError('照片僅接受 JPG、PNG、WebP')
        if len(photo)>4_200_000:raise ValueError('照片過大（請使用3MB以下）')
        try:base64.b64decode(photo.split(',',1)[1],validate=True)
        except Exception:raise ValueError('照片格式錯誤')
    with conn() as c:
        cur=c.execute('INSERT OR IGNORE INTO records(car,pair,time,kind,run,station,destination,note,source,photo,origin) VALUES(?,?,?,?,?,?,?,?,?,?,?)',tuple(v[k] for k in ['car','pair','time','kind','run','station','destination','note','source'])+(photo,origin))
        if cur.rowcount:audit(c,'record.create',v)
        return cur.rowcount

def logpoll(kind,status,message):
    with conn() as c:
        c.execute('INSERT INTO polls(time,kind,status,message) VALUES(?,?,?,?)',(now().isoformat(),kind,status,message[:600]))
        c.execute('DELETE FROM polls WHERE id NOT IN (SELECT id FROM polls ORDER BY id DESC LIMIT 3000)')

def fetch_json(url,headers=None):
    req=urllib.request.Request(url,headers={'User-Agent':'OrangeLineTracker/1.0',**(headers or {})})
    with urllib.request.urlopen(req,timeout=15) as r:
        raw=r.read(5_000_001)
        if len(raw)>5_000_000:raise ValueError('來源資料超過5MB')
        return json.loads(raw.decode('utf-8-sig'))

def poll():
    if not POLL_LOCK.acquire(False):return
    try:
        try:
            raw=fetch_json(PUBLIC_URL)
            if not isinstance(raw,list):raise ValueError('公開來源格式改變')
            rows=[r for r in raw if r.get('Destination','').removesuffix('站') in ['南勢角','迴龍','蘆洲']]
            with conn() as c:c.execute('INSERT OR REPLACE INTO live VALUES(?,?)',('public',json.dumps({'fetched':now().isoformat(),'rows':rows},ensure_ascii=False)))
            logpoll('public','ok',f'取得 {len(rows)} 筆橘線到站參考；不含實體車號，不計入車隊上線。')
        except Exception as e:logpoll('public','error',type(e).__name__+'：公開來源連線失敗，保留上次資料')
        try:
            request=urllib.request.Request(METRO_WEB_URL,headers={'User-Agent':'OrangeLineTracker/1.1'})
            with urllib.request.urlopen(request,timeout=20) as response:
                raw=response.read(3_000_001)
                if len(raw)>3_000_000:raise ValueError('公開動態頁超出大小限制')
                snapshot=parse_page(raw.decode('utf-8-sig'))
            age=(now()-parse_time(snapshot['updated'])).total_seconds()
            if age < -300 or age > 600:raise ValueError('公開動態頁資料時間已過期或異常，未產生新目擊')
            for row in snapshot['observations']:validate_record(row)
            count=sum(save_record(row,'web') for row in snapshot['observations'])
            with conn() as c:c.execute('INSERT OR REPLACE INTO live VALUES(?,?)',('metro_web',json.dumps({'fetched':now().isoformat(),**snapshot},ensure_ascii=False)))
            logpoll('web','ok',f'公開動態頁驗證 {len(snapshot["observations"])} 組追蹤車組，新增 {count} 筆；範圍外 {len(snapshot["outside"])} 組')
        except Exception as e:logpoll('web','error',str(e)[:200] if isinstance(e,ValueError) else type(e).__name__+'：公開動態頁連線失敗')
        # 專用接口採明確的正規化契約，絕不把 TrainNumber 自動視為實體車號。
        config=load_config(ROOT)
        fleet=config.get('fleet') or {}
        url=os.getenv('TRACKER_FEED_URL','').strip() or fleet.get('url','')
        if url:
            try:
                if urllib.parse.urlparse(url).scheme not in ['http','https']:raise ValueError('接口需為HTTP(S)')
                token=os.getenv(fleet.get('token_env','TRACKER_FEED_TOKEN'),'')
                data=fetch_json(url,{'Authorization':'Bearer '+token} if token else {})
                if fleet.get('fields'):data=normalize(data,fleet)
                if not isinstance(data,dict) or not isinstance(data.get('observations'),list):raise ValueError('需回傳 observations 陣列，詳見 adapter 文件')
                rows=data['observations']
                if len(rows)>1000:raise ValueError('單次最多1000筆')
                clean=[validate_record(d) for d in rows] # 先完整驗證，避免半批寫入
                count=0
                for d in clean:count+=save_record(d,'feed')
                logpoll('fleet','ok',f'驗證 {len(clean)} 筆，新增 {count} 筆；完整觀測日需另行確認')
            except Exception as e:logpoll('fleet','error',str(e)[:250] if isinstance(e,ValueError) else type(e).__name__+'：車號接口連線失敗')
        # 路網、線型、營運路線、時刻表等輔助來源獨立快取，不冒充車號證據。
        for source in config.get('references',[]):
            try:
                name=source['name'];interval=max(60,int(source.get('interval_seconds',86400)))
                with conn() as c:old=c.execute('SELECT value FROM live WHERE key=?',('ref:'+name,)).fetchone()
                if old and (now()-parse_time(json.loads(old['value'])['fetched'])).total_seconds()<interval:continue
                token=os.getenv(source.get('token_env','TRACKER_REFERENCE_TOKEN'),'')
                raw=fetch_json(source['url'],{'Authorization':'Bearer '+token} if token else {})
                with conn() as c:c.execute('INSERT OR REPLACE INTO live VALUES(?,?)',('ref:'+name,json.dumps({'name':name,'fetched':now().isoformat(),'data':raw},ensure_ascii=False)))
                logpoll('reference','ok',name+' 輔助資料更新成功')
            except Exception as e:logpoll('reference','error',source.get('name','輔助來源')+'：'+type(e).__name__+'，未更新')
    finally:POLL_LOCK.release()

def collector():
    while True:
        try:poll()
        except Exception as e:logpoll('fleet','error',type(e).__name__+'：來源設定無效，請檢查 sources.json')
        time.sleep(max(30,settings()['poll_seconds']))

def state():
    s=settings();records=getrows('records');eng=getrows('engineering')
    with conn() as c:
        cov={r['day']:r['value'] for r in c.execute('SELECT * FROM coverage')}
        details=[dict(r) for r in c.execute('SELECT * FROM coverage ORDER BY day DESC')]
        live=c.execute('SELECT value FROM live WHERE key=?',('public',)).fetchone()
        polls=[dict(r) for r in c.execute('SELECT * FROM polls ORDER BY id DESC LIMIT 30')]
        web=c.execute('SELECT value FROM live WHERE key=?',('metro_web',)).fetchone()
        references=[json.loads(r['value']) for r in c.execute("SELECT value FROM live WHERE key LIKE 'ref:%'")]
    fleet=summarize(records,cov,s,eng)
    # 總覽不傳照片；詳細資料接口才取得，減少手機傳輸。
    for f in fleet:
        for r in f['records']:r['photo']=bool(r.get('photo'))
    return {'now':now().isoformat(),'day':opday(now().isoformat(),s['cutoff']),'settings':s,'fleet':fleet,'public':json.loads(live['value']) if live else None,'polls':polls,'coverage':details,'feed_configured':bool(os.getenv('TRACKER_FEED_URL') or (load_config(ROOT).get('fleet') or {}).get('url')),'references':references,'metro_web':json.loads(web['value']) if web else None}

class Handler(BaseHTTPRequestHandler):
    server_version='OrangeTracker/1.0'
    def log_message(self,*args):pass
    def output(self,d,status=200,ctype='application/json; charset=utf-8'):
        payload=d if isinstance(d,bytes) else json.dumps(d,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(payload)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(payload)
    def authorized(self):return hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+KEY)
    def do_GET(self):
        path=urllib.parse.urlparse(self.path).path
        if path.startswith('/api/'):
            if not self.authorized():return self.output({'error':'請輸入存取金鑰'},401)
            if path=='/api/state':return self.output(state())
            if path.startswith('/api/record/'):
                try:i=int(path.split('/')[-1])
                except ValueError:return self.output({'error':'紀錄不存在'},404)
                with conn() as c:r=c.execute('SELECT * FROM records WHERE id=?',(i,)).fetchone()
                return self.output(dict(r) if r else {'error':'紀錄不存在'},200 if r else 404)
            if path=='/api/export':
                with conn() as c:
                    d={'version':1,'exported':now().isoformat(),'settings':settings(),'records':getrows('records'),'engineering':getrows('engineering'),'coverage':[dict(r) for r in c.execute('SELECT * FROM coverage')]}
                return self.output(d)
            if path=='/api/csv':
                f=io.StringIO();w=csv.writer(f);keys=['id','car','pair','time','kind','run','station','destination','note','source','origin'];w.writerow(keys)
                for r in getrows('records'):
                    w.writerow([("'"+str(r[k]) if str(r[k]).startswith(('=','+','-','@')) else r[k]) for k in keys])
                return self.output(('\ufeff'+f.getvalue()).encode(),ctype='text/csv; charset=utf-8')
            return self.output({'error':'找不到接口'},404)
        files={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/favicon.svg':'favicon.svg'}
        if path not in files:return self.output({'error':'找不到頁面'},404)
        f=ROOT/'static'/files[path]
        ctype={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml'}[f.suffix]
        self.output(f.read_bytes(),ctype=ctype)
    def do_POST(self):
        if not self.authorized():return self.output({'error':'存取金鑰錯誤'},401)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=20_000_000:raise ValueError('請求大小不合法（上限20MB）')
            d=json.loads(self.rfile.read(size))
            path=urllib.parse.urlparse(self.path).path
            if path=='/api/record':self.output({'added':save_record(d,photo=d.get('photo',''))});return
            if path=='/api/delete-record':
                with conn() as c:
                    r=c.execute('SELECT * FROM records WHERE id=?',(int(d['id']),)).fetchone()
                    if not r:raise ValueError('紀錄不存在')
                    audit(c,'record.delete',dict(r));c.execute('DELETE FROM records WHERE id=?',(int(d['id']),))
            elif path=='/api/engineering':
                p=pair(d['car']);start=parse_time(d['start']).isoformat();status=d['state']
                if status not in ['施工中','已完工','待施工','已取消']:raise ValueError('工程狀態錯誤')
                if len(d.get('note',''))>2000 or len(d.get('source',''))>2000:raise ValueError('工程內容過長')
                with conn() as c:
                    c.execute('INSERT INTO engineering(pair,start,state,note,source,created) VALUES(?,?,?,?,?,?)',(p,start,status,d.get('note',''),d.get('source',''),now().isoformat()));audit(c,'engineering.create',d)
            elif path=='/api/coverage':
                day=d['day'];parse_time(day+'T12:00:00')
                if day>=opday(now().isoformat(),settings()['cutoff']):raise ValueError('僅能確認已結束的營運日')
                value=float(d['value'])
                if value not in [0,1]:raise ValueError('觀測值錯誤')
                with conn() as c:c.execute('INSERT OR REPLACE INTO coverage VALUES(?,?,?)',(day,value,str(d.get('note',''))[:2000]));audit(c,'coverage.set',d)
            elif path=='/api/settings':
                limits={'cutoff':(0,6),'live_minutes':(1,60),'maintenance_after':(2,14),'poll_seconds':(30,3600),'prediction_min':(7,30)}
                clean={}
                for k,(lo,hi) in limits.items():
                    if k in d:
                        v=int(d[k])
                        if not lo<=v<=hi:raise ValueError(k+' 超出範圍')
                        clean[k]=v
                with conn() as c:
                    for k,v in clean.items():c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(k,json.dumps(v)))
                    audit(c,'settings.update',clean)
            elif path=='/api/import':
                # 新增合併，不覆寫既有資料；先驗證所有輸入再進行同一交易。
                if d.get('version')!=1:raise ValueError('不支援的備份版本')
                rows=d.get('records',[]);eng=d.get('engineering',[]);cov=d.get('coverage',[])
                if not all(isinstance(x,list) for x in [rows,eng,cov]):raise ValueError('備份格式錯誤')
                validated=[(validate_record(r),r.get('photo',''),r.get('origin','manual')) for r in rows]
                for r,photo,origin in validated:
                    if photo and (not isinstance(photo,str) or len(photo)>4_200_000 or not photo.startswith(('data:image/jpeg;base64,','data:image/png;base64,','data:image/webp;base64,'))):raise ValueError('備份照片格式不合法')
                    if photo:base64.b64decode(photo.split(',',1)[1],validate=True)
                    if origin not in ['manual','feed','web']:raise ValueError('備份來源錯誤')
                for e in eng:
                    pair(e['pair']);parse_time(e['start']);parse_time(e['created'])
                    if e['state'] not in ['施工中','已完工','待施工','已取消']:raise ValueError('工程格式錯誤')
                for v in cov:
                    parse_time(v['day']+'T12:00:00')
                    if v['value'] not in [0,1] or v['day']>=opday(now().isoformat(),settings()['cutoff']):raise ValueError('觀測日格式錯誤')
                with conn() as c:
                    for r,photo,origin in validated:c.execute('INSERT OR IGNORE INTO records(car,pair,time,kind,run,station,destination,note,source,photo,origin) VALUES(?,?,?,?,?,?,?,?,?,?,?)',tuple(r[k] for k in ['car','pair','time','kind','run','station','destination','note','source'])+(photo,origin))
                    for e in eng:
                        if not c.execute('SELECT 1 FROM engineering WHERE pair=? AND start=? AND state=? AND created=?',(pair(e['pair']),e['start'],e['state'],e['created'])).fetchone():c.execute('INSERT INTO engineering(pair,start,state,note,source,created) VALUES(?,?,?,?,?,?,?)',(pair(e['pair']),e['start'],e['state'],e.get('note',''),e.get('source',''),e['created']))
                    for v in cov:c.execute('INSERT OR IGNORE INTO coverage VALUES(?,?,?)',(v['day'],v['value'],v.get('note','')))
                    audit(c,'backup.import',{'records':len(rows)})
            elif path=='/api/poll':threading.Thread(target=poll,daemon=True).start()
            else:return self.output({'error':'找不到接口'},404)
            self.output({'ok':True})
        except (ValueError,KeyError,TypeError,OverflowError) as e:self.output({'error':str(e)},400)
        except Exception:self.output({'error':'伺服器處理失敗，資料未完成寫入'},500)

if __name__=='__main__':
    port=int(os.getenv('PORT','8787'));host=os.getenv('HOST','0.0.0.0')
    print(f'橘線追蹤已啟動：http://localhost:{port}\n存取金鑰位於 data/access-key.txt（請勿公開）',flush=True)
    threading.Thread(target=collector,daemon=True).start()
    ThreadingHTTPServer((host,port),Handler).serve_forever()
