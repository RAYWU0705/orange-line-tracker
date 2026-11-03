"""北捷公開動態頁 HTML 適配器。只接受頁面實際出現的非空車組元素。"""
from html.parser import HTMLParser
from datetime import datetime
import re
from core import TZ, pair
URL='https://web.metro.taipei/pages2026/WebCorner/O'
class MetroParser(HTMLParser):
    def __init__(self):
        super().__init__();self.depth=0;self.current=None;self.rows=[];self.update=False;self.update_text=''
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='span' and a.get('id')=='lblData':self.update=True
        if tag=='div':
            self.depth+=1
            value=a.get('data-cartweight','')
            m=re.fullmatch(r'O-(up|down)-(\d{3})/(\d{3})',value)
            if m and 'show' in a.get('class','').split():
                self.current={'depth':self.depth,'cars':[int(m[2]),int(m[3])],'direction':m[1],'destination':''}
        if self.current and tag=='img':
            alt=a.get('alt','')
            if alt.startswith('O-'):self.current['destination']=alt[2:].removesuffix('站')
    def handle_endtag(self,tag):
        if tag=='span':self.update=False
        if tag=='div':
            if self.current and self.current['depth']==self.depth:
                self.rows.append(self.current);self.current=None
            self.depth-=1
    def handle_data(self,data):
        if self.update:self.update_text+=data

def parse_page(html):
    parser=MetroParser();parser.feed(html)
    m=re.search(r'(\d{4})/(\d{1,2})/(\d{1,2})\s*(上午|下午)?\s*(\d{1,2}):(\d{2}):(\d{2})',parser.update_text)
    if not m:raise ValueError('公開動態頁缺少可驗證更新時間，暫停產生車號紀錄')
    y,mo,d,ap,h,mi,se=m.groups();h=int(h)
    if ap=='下午' and h<12:h+=12
    if ap=='上午' and h==12:h=0
    stamp=datetime(int(y),int(mo),int(d),h,int(mi),int(se),tzinfo=TZ).isoformat()
    result=[];outside=[];seen=set()
    for row in parser.rows:
        cars=row['cars'];p=min(cars)
        if p in seen:continue
        seen.add(p)
        if not 401<=p<=455 or sorted(cars)!=[p,p+1] or p%2!=1:
            outside.append(cars);continue
        # 頁面順序是方向端點，不代表已識別個別三節單元；存首端並在備註明確記錄。
        result.append({'car':cars[0],'time':stamp,'kind':'service','run':'','station':'','destination':row['destination'],'source':'北捷公開動態資訊頁','note':f'官網車組元素：{cars[0]}/{cars[1]}；方向代碼 {row["direction"]}。車號首端取自頁面順序，非親眼目擊；未提供車次與精確車站。'})
    if not parser.rows:raise ValueError('公開動態頁未取得列車元素，可能格式改變；不將空白視為全車隊停駛')
    return {'updated':stamp,'observations':result,'outside':outside,'visible_consists':len(seen)}
