"""Bounded GFS 2 m temperature and coherent 850 hPa horizontal advection.

Reuse the existing native NetCDF reader, spatial planner and cache eligibility.
No point mesh, raster recolouring, persistent cache or change to the wind source.
"""
from __future__ import annotations
import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import hashlib
import math
import struct
from time import monotonic
from .wind_netcdf import read_classic
from .wind_field_source import ENDPOINT, MAX_BYTES, MAX_NODES, WindFieldUnavailable, plan_subset, _cf_instant, _retry_delay, _cached_subset, utc

CAPABILITY = "weather.temperature.field_2m"
ADVECTION = "weather.temperature.advection_850hpa"
TEMP = "Temperature_height_above_ground"
ISOT = "Temperature_isobaric"
U, V, PRESSURE = "u-component_of_wind_isobaric", "v-component_of_wind_isobaric", "Pressure_surface"

class TemperatureFieldUnavailable(WindFieldUnavailable):
    """Stable secret-safe source/quality failure."""

def decode_grid(data, plan, *, isobaric=False, target=None, now=None):
    """Keep native numeric values; require coherent CF axes, units, height and time."""
    now = now or datetime.now(timezone.utc)
    try:
        vs = read_classic(data)["variables"]
        axes = {v["attributes"].get("standard_name"): (name, v) for name, v in vs.items() if v["attributes"].get("standard_name")}
        yn, yv = axes["latitude"]; xn, xv = axes["longitude"]
        tn, tv = axes["time"]; rn, rv = axes["forecast_reference_time"]
        valid, run = _cf_instant(tv), _cf_instant(rv)
        if run > now + timedelta(minutes=10) or now-run > timedelta(hours=24) or valid < run or valid-run > timedelta(hours=384):
            raise TemperatureFieldUnavailable("temperature_model_time_unavailable")
        if target is None and abs((valid-now).total_seconds()) > 10800 or target is not None and abs((valid-target).total_seconds()) > .5:
            raise TemperatureFieldUnavailable("temperature_native_time_unavailable")
        expiry = min(now+timedelta(minutes=30), run+timedelta(hours=24))
        if target is None: expiry = min(expiry, valid+timedelta(hours=3))
        if expiry <= now: raise TemperatureFieldUnavailable("temperature_model_time_unavailable")
        names = {ISOT:"K", U:"m/s", V:"m/s", PRESSURE:"Pa"} if isobaric else {TEMP:"K"}
        main = vs[ISOT if isobaric else TEMP]; zname = main["dimensions"][1]; z = vs[zname]
        if z["values"] != [85000. if isobaric else 2.] or z["attributes"].get("units") != ("Pa" if isobaric else "m"):
            raise TemperatureFieldUnavailable("temperature_wrong_vertical_reference")
        if yv["attributes"].get("units") != "degrees_north" or xv["attributes"].get("units") != "degrees_east":
            raise TemperatureFieldUnavailable("temperature_invalid_axes")
        mapping = main["attributes"]["grid_mapping"]; projection = vs[mapping]["attributes"]
        if projection.get("grid_mapping_name") != "latitude_longitude": raise TemperatureFieldUnavailable("temperature_projection")
        radius = projection.get("earth_radius", [6371229.])[0]
        if not 6e6 < radius < 7e6: raise TemperatureFieldUnavailable("temperature_earth_radius")
        for name, unit in names.items():
            var = vs[name]; a = var["attributes"]; prefix = [tn] if name == PRESSURE else [tn, zname]
            expected = prefix+[yv["dimensions"][0], xv["dimensions"][0]]
            if var["dimensions"] != expected or var["shape"][:-2] != [1]*len(prefix): raise TemperatureFieldUnavailable("temperature_incoherent_geometry")
            if a.get("units") != unit or a.get("grid_mapping") != mapping or a.get("scale_factor", [1.]) != [1.] or a.get("add_offset", [0.]) != [0.]:
                raise TemperatureFieldUnavailable("temperature_incoherent_units")
            if not {tn,rn,yn,xn,*([zname] if name != PRESSURE else [])}.issubset(set(a.get("coordinates", "").split())):
                raise TemperatureFieldUnavailable("temperature_incoherent_coordinates")
        center = (plan["west"]+plan["east"])/2
        xs = [(float(x)-center+180)%360-180+center for x in xv["values"]]; ys = list(map(float,yv["values"]))
        cols, rows = sorted(range(len(xs)),key=xs.__getitem__), sorted(range(len(ys)),key=ys.__getitem__)
        x, y = [xs[i] for i in cols], [ys[i] for i in rows]
        if min(len(x),len(y)) < 2 or len(x)*len(y)>MAX_NODES: raise TemperatureFieldUnavailable("temperature_grid_budget")
        for axis in [x,y]:
            step=axis[1]-axis[0]
            if step<=0 or any(not math.isfinite(v) for v in axis) or any(abs(b-a-step)>1e-5 for a,b in zip(axis,axis[1:])): raise TemperatureFieldUnavailable("temperature_irregular_grid")
        if y[0]<-90 or y[-1]>90: raise TemperatureFieldUnavailable("temperature_invalid_axes")
        arrays={name:[] for name in names}; mask=[]
        for row in rows:
            for col in cols:
                i=row*len(xs)+col; ok=True
                for name in names:
                    v=vs[name]["values"][i]; a=vs[name]["attributes"]
                    good=math.isfinite(v) and not any(v in a.get(k,[]) for k in ["_FillValue","missing_value"])
                    if name in [TEMP,ISOT]: good=good and v>0
                    arrays[name].append(v if good else 0.); ok=ok and good
                if isobaric: ok=ok and arrays[PRESSURE][-1]>=85000
                mask.append(int(ok))
        cyclic=bool(plan["cyclic"] and abs(x[-1]-x[0]+x[1]-x[0]-360)<1e-5)
        if plan["cyclic"] and not cyclic: raise TemperatureFieldUnavailable("temperature_incomplete_world")
        if cyclic:
            width=len(x)
            for array in [*arrays.values(),mask]: array[:]=[v for row in range(len(y)) for v in array[row*width:(row+1)*width]+[array[row*width]]]
            x.append(x[0]+360)
        if len(mask)>MAX_NODES or not any(mask): raise TemperatureFieldUnavailable("temperature_no_valid_nodes")
        return dict(id=hashlib.sha256(data).hexdigest()[:24], model_run=utc(run), valid_at=utc(valid), valid_until=utc(expiry), deadline=expiry,
                    grid=dict(crs="EPSG:4326",layout="row_major_south_first",longitudes=x,latitudes=y,valid_mask=mask,cyclic=cyclic),arrays=arrays,earth_radius_m=radius)
    except TemperatureFieldUnavailable: raise
    except (KeyError,TypeError,ValueError,IndexError,OverflowError,struct.error,UnicodeError) as error: raise TemperatureFieldUnavailable("temperature_invalid_native_contract") from error

def horizontal_advection(native):
    """Centred metric finite differences on ONE isobaric surface, K/h.

    Invalid/underground/polar stencils remain masked; cyclic longitude is periodic.
    This horizontal term is not total local dT/dt or a surface-temperature trend.
    """
    g=native["grid"]; x,y=g["longitudes"],g["latitudes"]; nx,ny=len(x),len(y); unique=nx-1 if g["cyclic"] else nx
    t,u,v=(native["arrays"][name] for name in [ISOT,U,V]); good=g["valid_mask"]; rates=[0.]*len(good); mask=[0]*len(good)
    step=math.radians(x[1]-x[0]); radius=native["earth_radius_m"]
    for row in range(1,ny-1):
        if abs(y[row])>88: continue
        dx=2*radius*math.cos(math.radians(y[row]))*step; dy=radius*math.radians(y[row+1]-y[row-1])
        for col in range(unique):
            if not g["cyclic"] and col in [0,nx-1]: continue
            i=row*nx+col; left=row*nx+(col-1)%unique; right=row*nx+(col+1)%unique
            if all(good[j] for j in [i,left,right,i-nx,i+nx]):
                rates[i]=-(u[i]*(t[right]-t[left])/dx+v[i]*(t[i+nx]-t[i-nx])/dy)*3600; mask[i]=1
        if g["cyclic"]: rates[row*nx+nx-1]=rates[row*nx]; mask[row*nx+nx-1]=mask[row*nx]
    return {"status":"ready" if any(mask) else "unavailable", "capability":ADVECTION, "unit":"K/h", "level":{"type":"isobaric","value":850,"unit":"hPa"},
            "model_run":native["model_run"],"valid_at":native["valid_at"],"valid_until":native["valid_until"],
            "method":"negative_horizontal_wind_dot_temperature_gradient_centred_spherical", "earth_radius_m":radius,
            "meaning":"horizontal_advection_not_total_local_temperature_change", "unavailable":None if any(mask) else {"code":"no_valid_advection_stencil"},
            "grid":{**g,"u":u,"v":v,"rate":rates,"valid_mask":mask}}

def frame_from_native(native, advection=None, reason="not_requested"):
    g=native["grid"]; values=native["arrays"][TEMP]; good=[v for v,m in zip(values,g["valid_mask"]) if m]
    return {"id":native["id"]+("-adv" if advection and advection["status"]=="ready" else ""),"capability":CAPABILITY,"kind":"model_forecast","model":"NOAA GFS","height_m":2,"unit":"K",
            "model_run":native["model_run"],"valid_at":native["valid_at"],"valid_until":native["valid_until"],"refresh_after_seconds":max(30,min(900,int((native["deadline"]-datetime.now(timezone.utc)).total_seconds()))),
            "native_resolution_degrees":.25,"model_output_interval_seconds":None,"temporal_resolution":"native_valid_time_no_temporal_interpolation","model_cycle_seconds":21600,"time_support":{"modes":["latest","at_time"],"temporal_interpolation":False,"delta_temperature_requires_two_coherent_valid_times":True},
            "grid":{**g,"values":values},"coverage":{"west":g["longitudes"][0],"east":g["longitudes"][-1],"south":g["latitudes"][0],"north":g["latitudes"][-1]},
            "temperature_range_kelvin":{"min":min(good),"max":max(good)},"advection":advection or {"status":"unavailable","capability":ADVECTION,"unavailable":{"code":reason}},
            "provenance":{"provider_id":"noaa_nws","model":"GFS","delivery":"Unidata NCSS","attribution":"NOAA / NCEP GFS · NSF Unidata / UCAR","source_url":"https://www.nco.ncep.noaa.gov/pmb/products/gfs/","delivery_url":"https://www.unidata.ucar.edu/","license":"NOAA public-domain data; Unidata research service","data_origin":"model","measurement_method":"numerical_model"}}

async def async_fetch_temperature(hass,bbox,*,include_advection=False,target=None):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from .const import DOMAIN
    from .diagnostic_center import record_http_exchange
    plan=plan_subset(bbox); time_key=utc(target) if target else "latest"; key=(time_key,include_advection,*plan.values())
    state=hass.data.setdefault(DOMAIN,{}).setdefault("temperature_field_runtime",{"cache":OrderedDict(),"inflight":{},"slot":asyncio.Semaphore(1),"cooldown":0.,"requests":0,"cache_hits":0,"active":0,"failures":0})
    def cached(want_advection):
        now=datetime.now(timezone.utc); view={"cache":OrderedDict(),"cooldown":state["cooldown"]}
        for old,(frame,tick,old_plan) in list(state["cache"].items()):
            if datetime.fromisoformat(frame["valid_until"].replace("Z","+00:00"))<=now: state["cache"].pop(old); continue
            if old[0]!=time_key or want_advection and frame["advection"]["status"]!="ready": continue
            pk=tuple(old_plan.values()); view["cache"][pk]=frame; view[("fetched",pk)]=tick
        hit=_cached_subset(view,bbox,plan)
        if hit:
            state["cache_hits"]+=1
            for ck,item in list(state["cache"].items()):
                if item[0] is hit[1]:state["cache"].move_to_end(ck);break
            return hit[1]
    hit=cached(include_advection)
    if hit: return hit
    if key in state["inflight"]: return await asyncio.shield(state["inflight"][key])
    if len(state["inflight"])>=3: raise TemperatureFieldUnavailable("temperature_transport_busy")
    async def get_native(names,height,when):
        if monotonic()<state["cooldown"]: raise TemperatureFieldUnavailable("temperature_provider_cooldown")
        params=[*[("var",name) for name in names],("vertCoord",str(height)),("time",when),("accept","netcdf3"),("horizStride",str(plan["stride"])),*[(n,str(plan[n])) for n in ["west","east","south","north"]]]
        state["requests"]+=1;started=monotonic();status=None
        try:
            async with async_get_clientsession(hass).get(ENDPOINT,params=params,timeout=28,headers={"User-Agent":"WeatherRouter/0.10 (personal research visualization)"}) as response:
                status=response.status
                if status in [429,503]: state["cooldown"]=monotonic()+_retry_delay(response.headers.get("Retry-After"));raise TemperatureFieldUnavailable("temperature_provider_overloaded")
                if status in [401,403]: raise TemperatureFieldUnavailable("temperature_source_access_denied")
                if status!=200: raise TemperatureFieldUnavailable("temperature_source_http_error")
                if response.content_length and response.content_length>MAX_BYTES: raise TemperatureFieldUnavailable("temperature_transport_budget")
                data=bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    data.extend(chunk)
                    if len(data)>MAX_BYTES: raise TemperatureFieldUnavailable("temperature_transport_budget")
            record_http_exchange(hass,"noaa_nws",started_monotonic=started,http_status=status,declared_response_bytes=len(data));return bytes(data)
        except Exception as error:
            state["failures"]+=1;record_http_exchange(hass,"noaa_nws",started_monotonic=started,http_status=status,failed=True)
            if not isinstance(error,TemperatureFieldUnavailable) or status is None or status>=500: state["cooldown"]=max(state["cooldown"],monotonic()+60)
            if isinstance(error,TemperatureFieldUnavailable): raise
            raise TemperatureFieldUnavailable("temperature_source_timeout" if isinstance(error,TimeoutError) else "temperature_source_unavailable") from error
    async def fetch():
        async with state["slot"]:
            warm=cached(include_advection)
            if warm:return warm
            state["active"]+=1;started=monotonic()
            try:
                base=cached(False)
                if base:
                    native={"id":base["id"].removesuffix("-adv"),"grid":{k:v for k,v in base["grid"].items() if k!="values"},"arrays":{TEMP:base["grid"]["values"]},"model_run":base["model_run"],"valid_at":base["valid_at"],"valid_until":base["valid_until"],"deadline":datetime.fromisoformat(base["valid_until"].replace("Z","+00:00"))}
                else:
                    raw=await get_native([TEMP],2,time_key if target else "present")
                    native=await hass.async_add_executor_job(lambda:decode_grid(raw,plan,target=target))
                adv=None; reason="not_requested"
                if include_advection:
                    try:
                        raw=await get_native([ISOT,U,V,PRESSURE],85000,native["valid_at"])
                        iso=await hass.async_add_executor_job(lambda:decode_grid(raw,plan,isobaric=True,target=datetime.fromisoformat(native["valid_at"].replace("Z","+00:00"))))
                        if any(iso[k]!=native[k] for k in ["model_run","valid_at"]) or any(iso["grid"][k]!=native["grid"][k] for k in ["latitudes","longitudes","crs","layout","cyclic"]):raise TemperatureFieldUnavailable("temperature_advection_incoherent_model_or_grid")
                        adv=await hass.async_add_executor_job(horizontal_advection,iso)
                        adv["valid_until"]=min(iso["valid_until"],native["valid_until"])
                    except (TemperatureFieldUnavailable,WindFieldUnavailable) as error:reason=str(error)
                frame=frame_from_native(native,adv,reason);frame["delivery_diagnostics"]={"upstream_requests":state["requests"],"cache_hits":state["cache_hits"],"cache_limit":6,"cache_budget_bytes":12*1048576,"prepare_and_fetch_ms":round((monotonic()-started)*1000,2)}
                if include_advection and frame["advection"]["status"]!="ready":frame["refresh_after_seconds"]=min(frame["refresh_after_seconds"],60)
                state["cache"][key]=(frame,monotonic(),plan);state["cache"].move_to_end(key)
                def estimate():return sum(len(item[0]["grid"]["values"])*(144 if item[0]["advection"]["status"]=="ready" else 40)+8192 for item in state["cache"].values())
                while len(state["cache"])>6 or estimate()>12*1048576:state["cache"].popitem(last=False)
                return frame
            finally:state["active"]-=1
    task=hass.async_create_task(fetch());state["inflight"][key]=task
    def completed(done):
        if state["inflight"].get(key) is done:state["inflight"].pop(key,None)
        if not done.cancelled():done.exception()
    task.add_done_callback(completed)
    return await asyncio.shield(task)
