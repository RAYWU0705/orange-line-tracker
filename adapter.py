"""可設定欄位映射；官方核准後依實際文件設定，不猜測代碼意義。"""
import json, os
from pathlib import Path
from datetime import datetime
from core import TZ, pair

def pick(obj,path,default=None):
    if not path:return obj
    for key in path.split('.'):
        try:obj=obj[int(key)] if isinstance(obj,list) else obj[key]
        except (KeyError,IndexError,TypeError,ValueError):return default
    return obj

def normalize(raw,config):
    rows=pick(raw,config.get('items_path',''))
    if not isinstance(rows,list):raise ValueError('items_path 必須對應陣列')
    fields=config.get('fields',{})
    if not fields.get('car') or not fields.get('time'):raise ValueError('必須明確設定實體 car 與 time 欄位，不能用車次替代')
    result=[]
    for row in rows:
        if config.get('line_field') and str(pick(row,config['line_field']))!=str(config.get('line_value','O')):continue
        code=str(pick(row,fields['car'],''))
        if config.get('car_map'):
            if code not in config['car_map']:continue
            car=config['car_map'][code]
        else:
            try:car=int(code)
            except ValueError:raise ValueError('車號代碼需透過 car_map 明確對照')
            try:pair(car)
            except ValueError:continue
        d={k:pick(row,v,'') for k,v in fields.items()};d['car']=car
        if config.get('time_format'):
            d['time']=datetime.strptime(str(d['time']),config['time_format']).replace(tzinfo=TZ).isoformat()
        d['kind']=config.get('kind','service');d['source']=config.get('name','車號資料接口')
        result.append(d)
    return {'observations':result}

def load_config(root):
    p=Path(root)/'sources.json'
    return json.loads(p.read_text('utf-8')) if p.exists() else {'fleet':None,'references':[]}
