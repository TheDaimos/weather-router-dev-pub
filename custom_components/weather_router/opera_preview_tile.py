"""Isolated, unverified OPERA RATE comparison PNG. Never a scientific tile."""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
from math import pi
from pathlib import Path


class PreviewBlocked(ValueError):
    pass


def render_preview(path, *, digest, grid, projection, dataset_path,
                   x, y, z, hypothesis, include_statistics=False):
    """Two clearly distinct storage-row hypotheses, never scientific approval."""
    if hypothesis not in ("north_first", "south_first"):
        raise PreviewBlocked("invalid_hypothesis")
    if any(type(v) is not int for v in (x,y,z)) or not 0 <= z <= 20 or not 0 <= x < 2**z or not 0 <= y < 2**z:
        raise PreviewBlocked("invalid_tile")
    source=Path(path)
    if source.is_symlink() or not source.is_file() or not 0 < source.stat().st_size <= 12*1024*1024:
        raise PreviewBlocked("invalid_source")
    if not isinstance(digest,str) or len(digest)!=64 or sha256(source.read_bytes()).hexdigest()!=digest:
        raise PreviewBlocked("source_digest_mismatch")
    try:
        import numpy as np
        from pyproj import Transformer,CRS
        from PIL import Image
        from .opera_odim_pixels import decode_odim_window
        if "+proj=laea" not in projection.lower().split():
            raise PreviewBlocked("unverified_projection")
        if not grid.row_zero_north or grid.width*grid.height>25_000_000:
            raise PreviewBlocked("invalid_grid")
        coord=(np.arange(256)+0.5)/256
        lon=((x+coord)/(2**z))*360-180
        lat=np.degrees(np.arctan(np.sinh(pi*(1-2*(y+coord)/(2**z)))))
        lons,lats=np.meshgrid(lon,lat)
        xx,yy=Transformer.from_crs(CRS.from_epsg(4326),CRS.from_user_input(projection),always_xy=True).transform(lons,lats)
        left,bottom,right,top=grid.bounds
        dx,dy=grid.pixel_size
        finite=np.isfinite(xx)&np.isfinite(yy)
        col=np.floor(np.where(finite,(xx-left)/dx,-1)).astype("int64")
        northrow=np.floor(np.where(finite,(top-yy)/dy,-1)).astype("int64")
        inside=finite&(col>=0)&(northrow>=0)&(col<grid.width)&(northrow<grid.height)
        storedrow=northrow if hypothesis=="north_first" else grid.height-1-northrow
        rgba=np.zeros((256,256,4),dtype=np.uint8)
        stats={"total_pixels": 65536, "valid_pixels": 0, "nodata_pixels": 0,
               "undetect_pixels": 0, "transparent_pixels": 65536,
               "precipitation_pixels": 0, "minimum_precipitation": None,
               "maximum_precipitation": None, "png_bytes": 0}
        if inside.any():
            # Limit *each* HDF5 window, not the overall geographic span of
            # the output tile. Very low zooms can cover the whole OPERA grid.
            # Process scanlines in small bounded source windows so that the
            # decoder's one-million-pixel safety limit remains unchanged.
            values=np.zeros((256,256),dtype=float)
            mask=np.zeros((256,256),dtype=bool)
            nodata_total=0
            undetect_total=0
            def render_region(row0,row1,col0,col1):
                nonlocal nodata_total, undetect_total
                selected=inside[row0:row1,col0:col1]
                if not selected.any():
                    return
                relative_rows,relative_cols=np.nonzero(selected)
                output_rows=relative_rows+row0
                output_cols=relative_cols+col0
                xs=col[output_rows,output_cols]
                ys=storedrow[output_rows,output_cols]
                x0,x1=int(xs.min()),int(xs.max())+1
                y0,y1=int(ys.min()),int(ys.max())+1
                if (x1-x0)*(y1-y0)>1024*1024:
                    # Split only the output region; the HDF5 cap still
                    # applies to every individual native decoder call.
                    if row1-row0>=col1-col0 and row1-row0>1:
                        mid=(row0+row1)//2
                        render_region(row0,mid,col0,col1)
                        render_region(mid,row1,col0,col1)
                    elif col1-col0>1:
                        mid=(col0+col1)//2
                        render_region(row0,row1,col0,mid)
                        render_region(row0,row1,mid,col1)
                    else:
                        raise PreviewBlocked("window_too_large")
                    return
                win=decode_odim_window(source,dataset_path=dataset_path,
                    quantity="RATE",x=x0,y=y0,width=x1-x0,height=y1-y0)
                local_x=xs-x0
                local_y=ys-y0
                no=win.nodata_mask[local_y,local_x]
                un=win.undetect_mask[local_y,local_x]
                nan=win.nan_mask[local_y,local_x]
                sampled=win.values[local_y,local_x]
                valid=(~no)&(~un)&(~nan)&np.isfinite(sampled)&(sampled>=0)
                values[output_rows,output_cols]=np.where(valid,sampled,0)
                mask[output_rows,output_cols]=valid
                nodata_total+=int(np.count_nonzero(no))
                undetect_total+=int(np.count_nonzero(un&~no))
            render_region(0,256,0,256)
            intensity=np.clip(values/50,0,1)
            rgba[:,:,0]=np.where(mask,np.round(255*intensity),0).astype("uint8")
            rgba[:,:,2]=np.where(mask,np.round(255*(1-intensity)),0).astype("uint8")
            rgba[:,:,3]=np.where(mask,255,0).astype("uint8")
            if include_statistics:
                stats["nodata_pixels"]=nodata_total
                stats["undetect_pixels"]=undetect_total
                stats["valid_pixels"]=int(np.count_nonzero(mask))
                stats["precipitation_pixels"]=int(np.count_nonzero(mask & (values>0)))
                if mask.any():
                    stats["minimum_precipitation"]=float(values[mask].min())
                    stats["maximum_precipitation"]=float(values[mask].max())
        out=BytesIO()
        Image.fromarray(rgba,mode="RGBA").save(out,format="PNG")
        payload=out.getvalue()
        if len(payload)>512*1024:
            raise PreviewBlocked("png_limit")
        if include_statistics:
            stats["transparent_pixels"]=int(np.count_nonzero(rgba[:,:,3]==0))
            stats["png_bytes"]=len(payload)
            return payload,stats
        return payload
    except PreviewBlocked:
        raise
    except Exception as exc:
        raise PreviewBlocked("render_failed") from exc


# Separate URL and authorization from the normal scientific OPERA tile view.
# This import is reached only when Home Assistant loads its integration.
import asyncio
from functools import partial
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from .opera_tile_access import TileAccessDenied, assert_authorized, validated_route
from .opera_tile_http import OdimRateTileRegistration
from datetime import datetime, timezone


class OperaPreviewTileView(HomeAssistantView):
    url = "/api/weather_router/opera_preview/RATE/{stamp}/{hypothesis}/{z}/{x}/{y}.png"
    name = "api:weather_router:opera_preview"
    requires_auth = True
    cors_allowed = False

    def __init__(self, hass, *, registry_lookup, is_diagnostic, enabled,
                 provider_enabled, permitted, max_age_seconds=lambda: 1500):
        self.hass = hass
        self.registry_lookup = registry_lookup
        self.is_diagnostic = is_diagnostic
        self.enabled = enabled
        self.provider_enabled = provider_enabled
        self.permitted = permitted
        self.max_age_seconds = max_age_seconds
        self._slots = asyncio.Semaphore(2)

    def _authorize(self, request, user, stamp, entry):
        if (not self.enabled()
                or not self.provider_enabled()
                or user is None or getattr(user, "is_admin", False) is not True
                or self.permitted(user, "RATE") is not True
                or self.registry_lookup("RATE",stamp) is not entry
                or self.is_diagnostic("RATE",stamp) is not True):
            raise web.HTTPForbidden()
        try:
            assert_authorized(authenticated_user=user,
                              profile_and_provider_allowed=True,
                              valid_at=entry.frame.valid_at,
                              now=datetime.now(timezone.utc), max_age_seconds=self.max_age_seconds())
        except TileAccessDenied as exc:
            raise web.HTTPForbidden() from exc

    async def get(self, request, stamp, hypothesis, z, x, y):
        if hypothesis not in ("north_first", "south_first"):
            raise web.HTTPForbidden()
        if not self.enabled():
            raise web.HTTPForbidden()
        user=request.get("hass_user")
        if user is None:
            raise web.HTTPUnauthorized()
        if getattr(user,"is_admin",False) is not True:
            raise web.HTTPForbidden()
        try:
            zn,xn,yn=validated_route(product="RATE",stamp=stamp,z=z,x=x,y=y,
                                      query_present=bool(request.query))
        except TileAccessDenied as exc:
            raise web.HTTPForbidden() from exc
        entry=self.registry_lookup("RATE",stamp)
        if not isinstance(entry,OdimRateTileRegistration):
            raise web.HTTPForbidden()
        self._authorize(request,user,stamp,entry)
        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=0.2)
        except asyncio.TimeoutError as exc:
            raise web.HTTPServiceUnavailable() from exc
        try:
            self._authorize(request,user,stamp,entry)
            work=partial(render_preview,entry.frame.path,digest=entry.frame.digest,
                         grid=entry.grid,projection=entry.projection,
                         dataset_path=entry.dataset_path,
                         x=xn,y=yn,z=zn,hypothesis=hypothesis)
            task=asyncio.ensure_future(self.hass.async_add_executor_job(work))
        except BaseException:
            self._slots.release()
            raise
        def completed(done):
            try:
                if not done.cancelled():
                    done.exception()  # observe late errors after request deadline
            finally:
                self._slots.release()
        task.add_done_callback(completed)
        try:
            png=await asyncio.wait_for(asyncio.shield(task),timeout=3.0)
        except asyncio.TimeoutError as exc:
            raise web.HTTPServiceUnavailable() from exc
        except PreviewBlocked as exc:
            raise web.HTTPServiceUnavailable() from exc
        # Revocation or disable during a queued/native render forbids delivery.
        self._authorize(request,user,stamp,entry)
        if not isinstance(png,bytes) or not 0<len(png)<=512*1024:
            raise web.HTTPServiceUnavailable()
        return web.Response(body=png,content_type="image/png",headers={
            "Cache-Control":"no-store, private",
            "X-Content-Type-Options":"nosniff",
            "X-WeatherRouter-Scientific-Status":"UNVERIFIED / ENTWICKLUNGSVORSCHAU",
            "X-WeatherRouter-Orientation-Hypothesis":hypothesis,
            "X-WeatherRouter-Product":"RATE",
        })
