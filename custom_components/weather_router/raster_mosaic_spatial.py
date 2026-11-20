"""Additive WR V2 spatial execution plans; selection/time stay in existing policy.

Whole viewport first, independent source/image/mask budgets. GR executes these
plans and masks; no colour/transparency inference and no competing routing.
"""
from __future__ import annotations
import base64
from datetime import datetime, timezone, timedelta
from math import floor,ceil
from time import perf_counter
from .nasa_mosaic import _y,tile_bounds,overlaps,NASA,MAX_TILES


def projected_view(viewport):
    l=(viewport['west']+180)/360;r=(viewport['east']+180)/360
    if r<=l:r+=1
    t,b=_y(viewport['north']),_y(viewport['south'])
    width=min(1,(r-l)*1.3);height=(b-t)*1.3
    cx,cy=(l+r)/2,(t+b)/2
    left,right=(0.,1.) if width>=1 else (cx-width/2,cx+width/2)
    return {'visible':(l,t,r,b),'padded':(left,max(0,cy-height/2),right,min(1,cy+height/2))}


def inventory(view,z):
    n=2**z;l,t,r,b=view['padded'];vl,vt,vr,vb=view['visible'];result={}
    for xx in range(floor(l*n),ceil(r*n)):
        for y in range(max(0,floor(t*n)),min(n,ceil(b*n))):
            x=xx%n;visible=xx/n<vr and (xx+1)/n>vl and y/n<vb and (y+1)/n>vt
            result[(x,y)]=result.get((x,y),False) or visible
    return [(x,y,visible) for (x,y),visible in sorted(result.items(),key=lambda p:(not p[1],p[0][1],p[0][0]))]


def _merge(intervals):
    result=[]
    for a,b in sorted(intervals):
        if b<=a:continue
        if result and a<=result[-1][1]:result[-1]=(result[-1][0],max(b,result[-1][1]))
        else:result.append((a,b))
    return result


def _segments(left,right,n):
    if right-left>=n:return [(0,n)]
    width=right-left
    left%=n;right=left+width
    return [(left,min(n,right))]+([(0,right-n)] if right>n else [])


class RadarMask:
    def __init__(self,coverage,boxes,valid_until,unknown=False):
        self.coverage=coverage;self.boxes=boxes;self.unknown=unknown
        self.zoom=coverage.zoom if coverage else 6
        self.size=128;self.n=2**self.zoom*self.size
        self.valid_until=valid_until
        self.rows={}
        if coverage:
            for tile in coverage.tiles:
                bits=base64.b64decode(tile['bits']);x0=tile['x']*self.size;y0=tile['y']*self.size
                for y in range(self.size):
                    run=None;row=[]
                    for x in range(self.size):
                        bit=(bits[(y*self.size+x)//8]>>(x%8))&1
                        if bit and run is None:run=x
                        if not bit and run is not None:row.append((x0+run,x0+x));run=None
                    if run is not None:row.append((x0+run,x0+self.size))
                    if row:self.rows.setdefault(y0+y,[]).extend(row)
        self.ranges=[]
        for box in boxes:
            if box.get('scope')=='global':b=dict(west=-180,east=180,south=-85.05112878,north=85.05112878)
            else:b=box.get('bbox',{})
            if not all(k in b for k in ('west','east','south','north')):self.unknown=True;continue
            l=floor((b['west']+180)/360*self.n);r=ceil((b['east']+180)/360*self.n)
            if r<=l:r+=self.n
            segments=_segments(l,r,self.n)
            self.ranges.append((max(0,floor(_y(b['north'])*self.n)),min(self.n,ceil(_y(b['south'])*self.n)),segments))

    def area(self,box):
        l,t,r,b=box;n=self.n
        segments=_segments(floor(l*n),ceil(r*n),n)
        y0,y1=max(0,floor(t*n)),min(n,ceil(b*n))
        total=sum(c-a for a,c in segments)*(y1-y0)
        if self.unknown:return {'requested_cells':total,'reserved_cells':total,'allowed_cells':0}
        reserved=0
        for y in range(y0,y1):
            intervals=list(self.rows.get(y,()))
            for top,bottom,parts in self.ranges:
                if top<=y<bottom:intervals.extend(parts)
            for a,c in _merge(intervals):
                for left,right in segments:reserved+=max(0,min(c,right)-max(a,left))
        return {'requested_cells':total,'reserved_cells':reserved,'allowed_cells':max(0,total-reserved)}

    def wire(self,view):
        l,t,r,b=view['padded'];visible=[];n=2**self.zoom
        for tile in self.coverage.tiles if self.coverage else ():
            if not (tile['y']/n<b and (tile['y']+1)/n>t):continue
            if not any(tile['x']/n+shift<r and (tile['x']+1)/n+shift>l for shift in (-1,0,1)):continue
            visible.append(dict(tile))
        return {'kind':'radar_observation_mask_v1','zoom':self.zoom,'size':self.size,
                'encoding':'base64_lsb','tiles':visible,'exclusions':self.boxes,
                'valid_until':self.valid_until if visible else None,'unknown':self.unknown,
                'opera':self.coverage.metadata() if self.coverage else None,
                'outside_mask_tiles':'unobserved_except_authoritative_exclusions'}


def complete_spatial_plan(query,sources,answer,accepted,now,*,nasa_enabled,parallelism,revision,uncertain=False,dwd_validity_cache=None):
    """Worker: extend the existing selected plan with complete source grids/masks."""
    from .raster_mosaic_policy import plan_raster_mosaic
    view=projected_view(query['context']);source_by_id={s['source_id']:s for s in sources}
    layers=answer['layers'];opera_source=source_by_id.get('opera/opera_rate_raster',{})
    coverage=opera_source.get('observation_mask')
    boxes=[]
    expired={r['source_id'] for r in answer.get('_internal_source_rejections',[]) if r['reason'] in ('source_stale','no_fresh_verified_frame')}
    for s in sources:
        if str(s.get('source_id','')).startswith('nasa_gibs/') or s.get('source_id') in expired:continue
        if s.get('source_id')=='opera/opera_rate_raster' and coverage is not None:continue
        b=s.get('machine_coverage')
        if isinstance(b,dict):boxes.append(dict(b))
        else:uncertain=True
    opera_expiry=opera_source.get('observation_valid_until')
    radar_mask=RadarMask(coverage,boxes,opera_expiry,unknown=uncertain)
    dwd={l['source_id']:dict(source_by_id[l['source_id']]['machine_coverage']) for l in layers
         if l['source_id'].startswith('dwd/') and l['source_id'] in source_by_id}
    remaining=query['limits']['max_tile_requests'];removed=[]
    regular=sorted((layer for layer in layers if layer['source_id']!=NASA),
                   key=lambda layer:0 if layer['source_id'].startswith('dwd/') else 1)
    for index,layer in enumerate(regular):
        available=max(0,remaining-(len(regular)-index-1))
        spec=layer['render'];sid=layer['source_id']
        desired=min(int(spec['max_zoom']),max(query['context']['tile_zoom'],5 if sid=='opera/opera_rate_raster' else 4 if sid.startswith('dwd/') else 0))
        candidates=[];z=desired
        for z in range(desired,-1,-1):
            l,t,r,b=view['padded'];n=2**z
            if (ceil(r*n)-floor(l*n))*(ceil(b*n)-floor(t*n))>65536:
                continue
            # Coarsen the entire plan before allocating unbounded inventories.
            bb=layer['coverage'];width=(bb['east']-bb['west'])%360 or 360
            estimate=(ceil(width/360*n)+2)*(ceil((_y(bb['south'])-_y(bb['north']))*n)+2)
            if min(estimate,(ceil(r*n)-floor(l*n))*(ceil(b*n)-floor(t*n)))>max(256,available*4):continue
            all_tiles=inventory(view,z)
            candidates=[(x,y,v) for x,y,v in all_tiles
                if overlaps(tile_bounds(z,x,y),layer['coverage'])]
            if sid=='opera/opera_rate_raster' and coverage:
                candidates=[(x,y,v) for x,y,v in candidates if any(a.any() for a in coverage.states(x,y,z,size=8))]
            if len(candidates)<=available:break
        complete=len(candidates)<=available
        if not complete:candidates=[]
        layer['raster_plan']={'kind':'source_tiles_v1','zoom':z,'tiles':[[x,y] for x,y,_ in candidates],
            'visible_tiles':sum(v for _,_,v in candidates),'padding_factor':1.3,
            'plan_complete':complete,'reason':None if complete else 'source_budget_unachievable'}
        remaining-=len(candidates)
        if sid=='opera/opera_rate_raster':
            layer['draw_exclusions']=list(dwd.values())
            if coverage:layer['observation_coverage']={**coverage.metadata(),'valid_until':opera_expiry}
            if complete and not candidates:
                removed.append(layer);answer.setdefault('_internal_source_rejections',[]).append({'source_id':sid,'reason':'outside_actual_observation_coverage'})
    for layer in removed:layers.remove(layer)
    if not layers:answer['reference_time']=None;answer['status']='unavailable'
    answer['spatial_contract_version']=2
    answer['spatial_planning']={'viewport':dict(query['context']),'projected_viewport':view['visible'],
        'projected_prefetch':view['padded'],'regular_source_budget_remaining':remaining,
        'radar_mask':{**(coverage.metadata() if coverage else {'status':'unavailable_or_no_admitted_opera'}),'valid_until':opera_expiry},
        'coverage_evidence':'observations_and_authoritative_envelopes_not_PNG_alpha',
        'unknown_primary_coverage':radar_mask.unknown}
    from .dwd_frame_mask import DWD_RADAR, cached_mask, pin_wms_run
    opera_layer=next((layer for layer in layers if layer['source_id']=='opera/opera_rate_raster'),None)
    dwd_layer=next((layer for layer in layers if layer['source_id']==DWD_RADAR),None)
    if opera_layer and dwd_layer and dwd.get(DWD_RADAR,{}).get('scope')=='bbox':
        mask_started = perf_counter()
        mask, status = cached_mask(dwd_validity_cache, dwd_layer)
        answer['spatial_planning']['dwd_validity'] = status
        answer['spatial_planning']['dwd_mask_lookup_ms'] = round((perf_counter()-mask_started)*1000, 3)
        answer['spatial_planning']['dwd_mask_cache_hit'] = mask is not None
        # Older clients still receive their unchanged draw_exclusions contract.
        opera_layer['dwd_priority_source'] = DWD_RADAR
        if mask:
            dwd_layer['dwd_nodata_mask'] = mask
            dwd_layer['tile_url'] = pin_wms_run(dwd_layer['tile_url'], mask['reference_at'])
            opera_layer['draw_exclusions'] = [
                {**envelope,'dwd_mask_source':DWD_RADAR} if source_id==DWD_RADAR else envelope
                for source_id,envelope in dwd.items()
            ]
    ordinary_nasa=next((layer for layer in layers if layer['source_id']==NASA),None)
    if not nasa_enabled and ordinary_nasa is None:return answer
    answer['nasa_mosaic']={'enabled':nasa_enabled,'mode':'radar_mask_v2','configured_parallelism':parallelism,
                         'deferred_tiles':True,'plan_complete':False,'pending_replan':False,
                         'plan_status':'waiting_for_authorized_source',
                         'data_exists':None, 'provider_admitted':False,
                         'coverage_reserved':False, 'tiles_authorized':False,
                         'actually_rendered':None}
    if ordinary_nasa is not None and not nasa_enabled:
        # Preserve the existing ordinary selection/consent/time decision; even
        # an ordinary satellite image must execute the WR radar exclusions.
        layer=ordinary_nasa;layers.remove(layer)
    else:
        candidates=[c for c in accepted if c['source_id']==NASA]
        if not candidates:
            answer['nasa_mosaic']['exclusion_reason']='nasa_source_not_admitted'
            return answer
        answer['nasa_mosaic']['data_exists']=True
        answer['nasa_mosaic']['provider_admitted']=True
        if query['time']['mode']!='latest_coherent':
            answer['nasa_mosaic']['exclusion_reason']='nasa_time_mode_not_latest'
            return answer
        viewport={k:query['context'][k] for k in ('west','east','north','south')}
        plan=plan_raster_mosaic(candidates,viewport=viewport,focus=query['context'].get('focus'),now=now,
              max_data_age_seconds=query['time']['max_data_age_seconds'],max_background_age_seconds=43200,
              max_time_delta_seconds=query['time'].get('max_time_delta_seconds',180),max_layers=1)
        if not plan['layers']:
            answer['nasa_mosaic']['exclusion_reason']='nasa_time_or_coverage_not_admitted'
            return answer
        layer=plan['layers'][0]
    for z in range(min(6,int(layer['render']['max_zoom'])),-1,-1):
        all_tiles=inventory(view,z)
        if len(all_tiles)<=MAX_TILES:break
    granted=[];fully_reserved=0
    for x,y,visible in all_tiles:
        n=2**z
        area=radar_mask.area((x/n,y/n,(x+1)/n,(y+1)/n))
        if area['allowed_cells']:granted.append((x,y,visible))
        else:fully_reserved+=1
    area=radar_mask.area(view['visible'])
    answer['nasa_mosaic'].update(area,area_unit='canonical_radar_mask_cells',mask_zoom=radar_mask.zoom,mask_size=radar_mask.size,
        plan_complete=not radar_mask.unknown,plan_status='protected_unknown_primary_coverage' if radar_mask.unknown else 'complete_authorized_area',
        planned_source_zoom=z,required_viewport_tiles=len(all_tiles),authorized_tile_count=len(granted),
        fully_reserved_tiles=fully_reserved,missing_planned_tiles=0,
        exclusion_reason='unknown_primary_coverage' if radar_mask.unknown else 'observed_or_verified_radar_envelopes',
        coverage_reserved=bool(area['reserved_cells']),
        tiles_authorized=bool(granted),
        source_valid_time_utc=layer['times']['valid_at'],
        pending_replan=False)
    if not granted:
        if not layers:answer['status']='unavailable';answer['reference_time']=None
        return answer
    wire=radar_mask.wire(view)
    layer['spatial_policy']={'kind':'radar_mask_v2','zoom':z,'tiles':[[x,y] for x,y,_ in granted],
        'padding_factor':1.3,'radar_mask':wire,'max_active_tiles':MAX_TILES,
        'reservation_status':'verified_observation_mask' if coverage else 'authoritative_envelopes'}
    layer['transport_policy']={'max_parallel_downloads':parallelism,'settings_revision':revision}
    layer['render']['min_zoom']=0;layer['render']['max_zoom']=z
    if coverage and opera_expiry and wire['tiles']:
        layer['times']['valid_until']=min(layer['times']['valid_until'],opera_expiry)
    if answer.get('reference_time'):
        primary=datetime.fromisoformat(answer['reference_time'].replace('Z','+00:00'))
        satellite=datetime.fromisoformat(layer['times']['valid_at'].replace('Z','+00:00'))
        layer['times']['reference_delta_seconds']=abs((satellite-primary).total_seconds())
    else:answer['reference_time']=layer['times']['valid_at']
    if nasa_enabled:layer['quality_note']='zeitlich_abweichend';layer['composition']['role']='background'
    layer['composition']['draw_order']=len(layers)
    if len(layers)<query['limits']['max_layers']:layers.append(layer)
    else:answer['nasa_mosaic'].update(plan_complete=False,pending_replan=False,exclusion_reason='layer_budget')
    if layers and answer['status']=='unavailable':answer['status']='partial'
    return answer
