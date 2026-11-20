"""Bounded public native legend metadata; no arbitrary nested provider payloads."""
from math import isfinite
import re

def normalize_native_legend(raw):
    result={}
    for key in ('title','unit','quantity','kind','source_title'):
        value=raw.get(key)
        if isinstance(value,str) and 0<len(value)<=160:result[key]=value
    entries=raw.get('entries')
    if isinstance(entries,list) and 0<len(entries)<=256:
        checked=[]
        for entry in entries:
            if not isinstance(entry,dict):return result
            value,label,color=entry.get('value'),entry.get('label'),entry.get('color')
            if (type(value) not in (int,float) or not isfinite(value) or
                not isinstance(label,str) or not 0<len(label)<=160 or
                not isinstance(color,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?',color)):
                return result
            checked.append({'value':value,'label':label,'color':color})
        result['entries']=checked
    ticks=raw.get('ticks')
    if isinstance(ticks,list) and len(ticks)<=16:
        result['ticks']=[{'position':t['position'],'label':t['label']} for t in ticks
            if isinstance(t,dict) and type(t.get('position')) in (int,float)
            and isfinite(t['position']) and 0<=t['position']<=1
            and isinstance(t.get('label'),str) and 0<len(t['label'])<=32]
    # Only one level and two physical phases; recursion is deliberately forbidden.
    scales=raw.get('scales')
    if isinstance(scales,list) and len(scales)<=2:
        result['scales']=[normalize_native_legend({k:v for k,v in s.items() if k!='scales'})
                          for s in scales if isinstance(s,dict)]
    return result
