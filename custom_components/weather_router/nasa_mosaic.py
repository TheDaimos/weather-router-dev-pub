"""WR-owned conservative tile reservations and bounded parallel IMERG metadata.

Envelopes reserve space, never assert wet/dry pixel validity. Unknown primary
coverage fails closed. No image bytes, scientific processing or persistent cache.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from math import asinh, atan, ceil, floor, isfinite, pi, sinh, tan, degrees, radians
from uuid import uuid4

OPTION = "nasa_imerg_complement"
NASA = "nasa_gibs/satellite_precipitation_imerg_30min"
MAX_TILES = 48
PARALLEL_OPTION = "nasa_max_parallel_downloads"
DEFAULT_PARALLEL = 6

def configured_parallel(options):
    value=options.get(PARALLEL_OPTION,DEFAULT_PARALLEL)
    return value if type(value) is int and 2<=value<=32 else DEFAULT_PARALLEL

def _y(lat):
    return (1-asinh(tan(radians(max(-85.05112878,min(85.05112878,lat)))))/pi)/2

def tile_bounds(z,x,y):
    n=2**z
    return {"west":x/n*360-180,"east":(x+1)/n*360-180,
            "north":degrees(atan(sinh(pi*(1-2*y/n)))),
            "south":degrees(atan(sinh(pi*(1-2*(y+1)/n))))}

def _segments(box):
    return [(box['west'],box['east'])] if box['west']<box['east'] else [(box['west'],180),(-180,box['east'])]

def overlaps(a,b):
    # Boundary-touching source tiles are conservatively reserved too.
    return (a['north']>=b['south']-1e-9 and a['south']<=b['north']+1e-9 and
            any(e>=w2-1e-9 and w<=e2+1e-9 for w,e in _segments(a) for w2,e2 in _segments(b)))

def authorized_tiles(viewport, zoom, reservations, *, uncertain=False, max_zoom=6):
    """Expand projected width/height by 1.30, enumerate only safe source tiles."""
    west=(viewport['west']+180)/360;east=(viewport['east']+180)/360
    if east<=west:east+=1
    top,bottom=_y(viewport['north']),_y(viewport['south'])
    width=min(1,(east-west)*1.3);height=(bottom-top)*1.3
    cx=(west+east)/2;cy=(top+bottom)/2
    left,right=(0.,1.) if width>=1 else (cx-width/2,cx+width/2)
    top,bottom=max(0,cy-height/2),min(1,cy+height/2)
    boxes=[]
    for item in reservations:
        coverage=item.get('machine_coverage')
        if not isinstance(coverage,dict):uncertain=True;continue
        if coverage.get('scope')=='global':boxes.append(dict(west=-180,east=180,south=-90,north=90))
        elif coverage.get('scope')=='bbox' and isinstance(coverage.get('bbox'),dict):
            b=coverage['bbox']
            if not all(type(b.get(k)) in (int,float) and isfinite(b[k]) for k in ('west','east','north','south')):uncertain=True
            else:boxes.append(b)
        else:uncertain=True
    # Prefer a source grid with useful free tiles, independently of display
    # zoom. At z0 a whole-world tile intersects every regional radar envelope.
    # Finer *whole* source tiles preserve exclusivity at low display zoom too.
    best=None
    if not uncertain:
        for z in range(0,min(6,max_zoom)+1):
            n=2**z
            xs=range(floor(left*n),ceil(right*n));ys=range(max(0,floor(top*n)),min(n,ceil(bottom*n)))
            if len(xs)*len(ys)>MAX_TILES:break
            allowed=[];visible_area=0.
            for x0 in xs:
                for y in ys:
                    x=x0%n;b=tile_bounds(z,x,y)
                    if any(overlaps(b,box) for box in boxes):continue
                    if [x,y] not in allowed:allowed.append([x,y])
                    # Compare safe area inside the actual view, not just padding.
                    vx0=(viewport['west']+180)/360;vx1=(viewport['east']+180)/360
                    if vx1<=vx0:vx1+=1
                    visible_area+=max(0,min((x0+1)/n,vx1)-max(x0/n,vx0))*max(0,min((y+1)/n,_y(viewport['south']))-max(y/n,_y(viewport['north'])))
            score=(round(visible_area,12),min(z,int(zoom)), -abs(z-int(zoom)))
            if best is None or score>best[0]:best=(score,z,allowed)
    z,tiles=(best[1],best[2]) if best else (min(6,max(0,int(zoom))),[])
    return {"kind":"exclusive_tiles_v1","zoom":z,"tiles":tiles,
            "padding_factor":1.3,"projected_viewport":[left,top,right,bottom],
            "reservation_basis":"conservative_verified_envelopes",
            "reservation_status":"unknown_primary_coverage" if uncertain else "verified_envelopes",
            "max_active_tiles":MAX_TILES}

class NasaMetadataPreparation:
    """One bounded job per HA runtime; parallel to radar, never on its critical path."""
    def __init__(self,on_ready=None):
        self.on_ready=on_ready
        self.task=None;self.payload=None;self.retrieved_at=None;self.started=-1e9;self.cycle=None;self.error=False

    def peek_or_start(self, fetch):
        now=asyncio.get_running_loop().time()
        if (self.task is None or self.task.done()) and now-self.started>=60:
            self.started=now;self.cycle=uuid4().hex;self.error=False
            async def prepare():
                try:
                    async with asyncio.timeout(15):value=await fetch()
                    if not isinstance(value,dict):raise ValueError('invalid_metadata')
                    self.payload=value;self.retrieved_at=datetime.now(timezone.utc).isoformat()
                    if self.on_ready:self.on_ready()
                except asyncio.CancelledError:raise
                except Exception:self.error=True
            self.task=asyncio.create_task(prepare())
        return self.payload

    def diagnostic(self):
        pending=self.task is not None and not self.task.done()
        return {"planning_cycle":self.cycle,"metadata_pending":pending,
                "metadata_state":"pending" if pending else "failed" if self.error else "ready" if self.payload else "not_started",
                "retry_after_seconds":2 if pending else None}

    def close(self):
        if self.task is not None:self.task.cancel()
        self.payload=None

async def complement_snapshot(query,sources,radar_answer,accepted,now, *, uncertain=False, parallelism=6, transport_revision=0):
    """Append separately time-authorized IMERG; never re-rank the radar plan."""
    from .raster_mosaic_policy import plan_raster_mosaic
    candidates=[c for c in accepted if c['source_id']==NASA]
    answer=radar_answer
    answer['nasa_mosaic']={"enabled":True,"mode":"exclusive_tiles_v1","deferred_tiles":True,"configured_parallelism":parallelism}
    if query['time']['mode']!='latest_coherent' or not candidates:return answer
    reservations=[s for s in sources if not str(s.get('source_id','')).startswith('nasa_gibs/')]
    for candidate in candidates:
        viewport={key:query['context'][key] for key in ('west','east','north','south')}
        plan=plan_raster_mosaic([candidate],viewport=viewport,focus=query['context'].get('focus'),now=now,
             max_data_age_seconds=query['time']['max_data_age_seconds'],max_background_age_seconds=43200,
             max_time_delta_seconds=query['time'].get('max_time_delta_seconds',180),max_layers=1)
        if not plan['layers']:continue
        layer=plan['layers'][0]
        policy=authorized_tiles(query['context'],query['context']['tile_zoom'],reservations,uncertain=uncertain,max_zoom=int(layer['render']['max_zoom']))
        answer['nasa_mosaic'].update(authorized_tile_count=len(policy['tiles']),reservation_status=policy['reservation_status'])
        if not policy['tiles'] or len(answer['layers'])>=query['limits']['max_layers']:continue
        layer['transport_policy']={'max_parallel_downloads':parallelism,'settings_revision':transport_revision};layer['spatial_policy']=policy;layer['render']['max_zoom']=policy['zoom']
        layer['render']['min_zoom']=0  # grant zoom is independent of map/display zoom
        layer['composition']['draw_order']=len(answer['layers']);layer['composition']['role']='background'
        if answer.get('reference_time'):
            primary=datetime.fromisoformat(answer['reference_time'].replace('Z','+00:00'))
            satellite=datetime.fromisoformat(layer['times']['valid_at'].replace('Z','+00:00'))
            layer['times']['reference_delta_seconds']=abs((satellite-primary).total_seconds())
        else:answer['reference_time']=plan['reference_time']
        layer['quality_note']='zeitlich_abweichend'
        answer['layers'].append(layer)
        if answer.get('status')=='unavailable':answer['status']='partial'
        answer['limitations'].append('IMERG: Satellitenschaetzung; nur exklusiv freigegebene Quellkacheln; eigene WR-Gueltigkeit.')
    return answer
