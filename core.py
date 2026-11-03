"""橘線追蹤：時間、推估及輸入驗證（無第三方套件）。"""
from datetime import datetime, timedelta, timezone
import math
TZ=timezone(timedelta(hours=8))
KINDS={'service','test','depot'}
DEFAULTS={'cutoff':4,'live_minutes':10,'maintenance_after':3,'poll_seconds':60,'coverage_min':0.9,'prediction_min':14}

def now(): return datetime.now(TZ)
def parse_time(value):
    dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    return dt.replace(tzinfo=TZ) if dt.tzinfo is None else dt.astimezone(TZ)
def opday(value,cutoff=4): return (parse_time(value)-timedelta(hours=cutoff)).date().isoformat()
def pair(car):
    n=int(car)
    if not 401<=n<=456: raise ValueError('車號須為 401–456')
    return n if n%2 else n-1

def branch(run):
    try:n=int(run)
    except (TypeError,ValueError):return '未判定'
    return '迴龍／南勢角' if 401<=n<=420 else '蘆洲／南勢角' if 430<=n<=449 else '未判定'

def validate_record(d):
    n=int(d.get('car',0));pair(n)
    dt=parse_time(d.get('time',''))
    if dt>now()+timedelta(minutes=5):raise ValueError('不能登記未來目擊')
    if d.get('kind','service') not in KINDS:raise ValueError('紀錄類型錯誤')
    out={'car':n,'pair':pair(n),'time':dt.isoformat(),'kind':d.get('kind','service')}
    for k in ['run','station','destination','note','source']:
        out[k]=str(d.get(k,'')).strip()
        if len(out[k])>2000:raise ValueError('欄位內容過長')
    return out

def maintenance(days,threshold=3):
    if days is None or days<threshold:return []
    names=[]
    if 1<=days<=3:names.append('三級檢修')
    if 3<=days<=7:names.append('四級檢修')
    if days>=14:names.append('五級檢修／大修')
    return names

def wilson(k,n):
    p=k/n;z=1.96;den=1+z*z/n
    mid=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [round(100*max(0,mid-half)),round(100*min(1,mid+half))]

def summarize(records,coverage,settings,engineerings,at=None):
    at=at or now();cut=settings['cutoff'];today=opday(at.isoformat(),cut)
    dates=[(parse_time(today+'T12:00:00')-timedelta(days=i)).date().isoformat() for i in range(1,31)]
    covered={d for d,v in coverage.items() if v>=settings['coverage_min'] and d<today}
    result=[]
    for p in range(401,456,2):
        allr=sorted([r for r in records if r['pair']==p],key=lambda r:r['time'])
        sr=[r for r in allr if r['kind']=='service' and parse_time(r['time'])<=at]
        last=sr[-1] if sr else None
        seen={opday(r['time'],cut) for r in sr}
        days=(parse_time(today+'T12:00:00').date()-parse_time(opday(last['time'],cut)+'T12:00:00').date()).days if last else None
        elapsed=(at-parse_time(last['time'])).total_seconds() if last else None
        live=elapsed is not None and 0<=elapsed<=settings['live_minutes']*60
        missing=[(parse_time(today+'T12:00:00')-timedelta(days=i)).date().isoformat() for i in range(1,days or 0)]
        gap_ok=bool(missing) and all(d in covered for d in missing)
        candidates=maintenance(days,settings['maintenance_after']) if gap_ok else []
        event=next((e for e in reversed(engineerings) if e['pair']==p),None)
        recovered=bool(event and any(parse_time(r['time'])>=parse_time(event['start']) for r in sr))
        engineering=dict(event,recovered=recovered) if event else None
        status='近期確認上線' if live else '今日曾上線' if today in seen else '疑似檢修' if candidates else '目前未見' if last else '尚無紀錄'
        sample=[d for d in dates if d in covered]
        k=sum(d in seen for d in sample);n=len(sample)
        # 僅在有足夠全車隊完整觀測日才把未見當作負樣本。
        prediction={'probability':None,'label':'資料不足','n':n,'k':k,'interval':None,'reason':f'近30日可用完整觀測 {n} 日；至少需 {settings["prediction_min"]} 日。'}
        if n>=settings['prediction_min']:
            prob=round(100*(k+1)/(n+2))
            prediction={'probability':prob,'label':'較可能' if prob>=67 else '較不可能' if prob<=33 else '普通','n':n,'k':k,'interval':wilson(k,n),'reason':f'完整觀測 {n} 日中有 {k} 日載客上線，採平滑歷史頻率；尚非經校準的預測模型。'}
        result.append({'pair':p,'cars':[p,p+1],'status':status,'live':live,'today':today in seen,'last':last,'days':days,'gap_complete':gap_ok,'maintenance':candidates,'engineering':engineering,'prediction':prediction,'seen_days':sorted(seen),'records':allr,'stats':{'last30':sum(d in seen for d in dates),'records':len(allr),'branch':{b:sum(branch(r['run'])==b for r in sr) for b in ['迴龍／南勢角','蘆洲／南勢角']}}})
    return result
