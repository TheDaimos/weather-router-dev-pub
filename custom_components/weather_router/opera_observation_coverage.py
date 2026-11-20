"""Frame-bound observation validity from original RATE masks, never PNG colours.

Uses the existing calibrated ODIM reader and the renderer's shared north-first
coordinates. Mixed or unknown cells protect radar. No persistence or new policy.
"""
from __future__ import annotations
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from threading import RLock
import base64
import math

BLOCK = 4
MASK_SIZE = 128
MASK_MAX_TILES = 256
_cache = OrderedDict()
_lock = RLock()


@dataclass(eq=False)
class ObservationCoverage:
    generation: str
    valid_at: str
    grid: object
    projection: str
    hull: dict
    counts: dict
    wet: object
    dry: object
    unknown: object
    zoom: int = 6
    tiles: tuple = ()

    def states(self, x, y, z, size=MASK_SIZE, detailed=False):
        import numpy as np
        from .opera_odim_tile import rate_tile_coordinates
        # Nine samples around each cell plus one coarse source-cell guard.
        # OR reduction protects every observed/unknown source block touched.
        _, _, finite, col, row = rate_tile_coordinates(self.grid, self.projection,
            x=x, y=y, z=z, tile_size=size*2, edges=True)
        rr=[row[dy:dy+2*size:2,dx:dx+2*size:2] for dy in range(3) for dx in range(3)]
        cc=[col[dy:dy+2*size:2,dx:dx+2*size:2] for dy in range(3) for dx in range(3)]
        valid=np.logical_and.reduce([finite[dy:dy+2*size:2,dx:dx+2*size:2] for dy in range(3) for dx in range(3)])
        x0=np.floor_divide(np.minimum.reduce(cc),BLOCK)-1
        x1=np.floor_divide(np.maximum.reduce(cc),BLOCK)+2
        y0=np.floor_divide(np.minimum.reduce(rr),BLOCK)-1
        y1=np.floor_divide(np.maximum.reduce(rr),BLOCK)+2
        def query(prefix):
            h,w=prefix.shape[0]-1,prefix.shape[1]-1
            a,b=np.clip(x0,0,w),np.clip(x1,0,w)
            c,d=np.clip(y0,0,h),np.clip(y1,0,h)
            return (prefix[d,b].astype(np.int64)-prefix[c,b]
                    -prefix[d,a]+prefix[c,a])>0
        wet=query(self.wet)
        dry=query(self.dry)&~wet
        observed=wet|dry
        unknown=(query(self.unknown)|~valid)&~observed
        if detailed:
            return np.where(wet,2,np.where(dry,1,np.where(unknown,3,0))).astype(np.uint8)
        return observed,unknown

    def metadata(self):
        return {'generation':self.generation,'valid_at':self.valid_at,
                'orientation':'north_first','source_block_pixels':BLOCK,
                'guard_source_blocks':1,
                'states':{'0':'no_observation','1':'dry_or_below_detection','2':'wet','3':'unknown'},
                'reduction':'any_observed_or_unknown_protects',
                'counts':dict(self.counts),'grid_envelope':dict(self.hull),
                'mask_zoom':self.zoom,'mask_size':MASK_SIZE,
                'protected_mask_tiles':len(self.tiles),
                'quality_policy':'ODIM_RATE_nodata_undetect_and_numeric_validity'}


def _hull(grid, projection):
    import numpy as np
    from .opera_odim_tile import rate_projection
    from pyproj.enums import TransformDirection
    left,bottom,right,top=grid.bounds
    # Densify the actual existing projected grid edges, not only four corners.
    nx=max(2,math.ceil(grid.width/BLOCK));ny=max(2,math.ceil(grid.height/BLOCK))
    xs=np.r_[np.linspace(left,right,nx),np.linspace(left,right,nx),np.full(ny,left),np.full(ny,right)]
    ys=np.r_[np.full(nx,bottom),np.full(nx,top),np.linspace(bottom,top,ny),np.linspace(bottom,top,ny)]
    lon,lat=rate_projection(projection).transform(xs,ys,direction=TransformDirection.INVERSE)
    if not np.isfinite(lon).all() or not np.isfinite(lat).all():raise ValueError('mask_grid_envelope_invalid')
    pad=max(grid.pixel_size)*BLOCK/100000
    return dict(west=max(-180,float(lon.min())-pad/max(.1,math.cos(math.radians(float(lat.max()))))),
                east=min(180,float(lon.max())+pad/max(.1,math.cos(math.radians(float(lat.max()))))),
                south=max(-85,float(lat.min())-pad),north=min(85,float(lat.max())+pad))


def build_observation_coverage(registration):
    """Run in the existing trusted registration worker, only for an admitted frame."""
    import numpy as np
    from .opera_odim_pixels import decode_odim_window,MAX_WINDOW_PIXELS
    from .nasa_mosaic import tile_bounds,overlaps,_y
    frame=registration.frame;grid=registration.grid
    key=(frame.digest,registration.dataset_path,registration.projection,grid.bounds,grid.width,grid.height)
    if not grid.row_zero_north or not registration.row_orientation_verified:
        raise ValueError('mask_orientation_not_admitted')
    with _lock:
        if key in _cache:
            _cache.move_to_end(key);return _cache[key]
        if (frame.path.is_symlink() or not frame.path.is_file()
                or frame.path.stat().st_size>12*1024*1024
                or sha256(frame.path.read_bytes()).hexdigest()!=frame.digest):
            raise ValueError('mask_source_digest_mismatch')
        h,w=grid.height,grid.width
        if not 0<h*w<=25_000_000:raise ValueError('mask_grid_budget')
        wet_blocks=np.zeros(((h+BLOCK-1)//BLOCK,(w+BLOCK-1)//BLOCK),bool)
        dry_blocks=np.zeros_like(wet_blocks)
        unknown=np.zeros_like(wet_blocks)
        counts={k:0 for k in ('wet','dry','undetect','nodata','unknown')}
        chunk=max(BLOCK,(MAX_WINDOW_PIXELS//w//BLOCK)*BLOCK)
        for y in range(0,h,chunk):
            height=min(chunk,h-y)
            win=decode_odim_window(frame.path,dataset_path=registration.dataset_path,
                 quantity='RATE',x=0,y=y,width=w,height=height)
            finite=np.isfinite(win.values)
            wet=finite&(win.values>0)
            dry=finite&(win.values==0)
            obs=wet|dry|win.undetect_mask
            unk=~(obs|win.nodata_mask)
            for name,array in [('wet',wet),('dry',dry),('undetect',win.undetect_mask),('nodata',win.nodata_mask),('unknown',unk)]:
                counts[name]+=int(np.count_nonzero(array))
            def reduce(array):
                pad=np.pad(array,((0,(-height)%BLOCK),(0,(-w)%BLOCK)))
                return pad.reshape(pad.shape[0]//BLOCK,BLOCK,pad.shape[1]//BLOCK,BLOCK).any(axis=(1,3))
            a=reduce(wet);b=reduce(unk);d=reduce(dry|win.undetect_mask)
            wet_blocks[y//BLOCK:y//BLOCK+a.shape[0]]=a
            dry_blocks[y//BLOCK:y//BLOCK+d.shape[0]]=d
            unknown[y//BLOCK:y//BLOCK+b.shape[0]]=b
        def prefix(array):
            result=np.pad(array.astype(np.uint32).cumsum(axis=0,dtype=np.uint32).cumsum(axis=1,dtype=np.uint32),((1,0),(1,0)))
            result.setflags(write=False);return result
        mask=ObservationCoverage(frame.digest,frame.valid_at.isoformat(),grid,
              registration.projection,_hull(grid,registration.projection),counts,prefix(wet_blocks),prefix(dry_blocks),prefix(unknown))
        for z in range(6,-1,-1):
            n=2**z;b=mask.hull
            xs=range(max(0,math.floor((b['west']+180)/360*n)),min(n,math.ceil((b['east']+180)/360*n)))
            ys=range(max(0,math.floor(_y(b['north'])*n)),min(n,math.ceil(_y(b['south'])*n)))
            if len(xs)*len(ys)<=MASK_MAX_TILES:break
        mask.zoom=z;tiles=[]
        for x in xs:
            for y in ys:
                states=mask.states(x,y,z,detailed=True)
                blocked=states!=0
                if not blocked.any():continue
                packed=np.packbits(blocked.ravel(),bitorder='little').tobytes()
                tiles.append({'x':x,'y':y,'bits':base64.b64encode(packed).decode('ascii'),
                    'observed_cells':int(((states==1)|(states==2)).sum()),
                    'wet_cells':int((states==2).sum()),'dry_cells':int((states==1).sum()),
                    'unknown_cells':int((states==3).sum())})
        mask.tiles=tuple(tiles);_cache[key]=mask
        while len(_cache)>2:_cache.popitem(last=False)
        return mask
