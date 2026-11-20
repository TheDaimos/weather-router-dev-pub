"""Additive authenticated V2 numeric temperature capability; core owns policy."""
from datetime import datetime, timezone
import asyncio
import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from .consumer_profiles import profile_allows_capability, profile_allows_candidate, profile_allows_provider
from .temperature_field_source import CAPABILITY, ADVECTION, TemperatureFieldUnavailable, async_fetch_temperature
from .wind_field_source import plan_subset, WindFieldUnavailable

META={"family":"field","phenomena":["temperature"],"resource_types":["scalar_grid"]}
ADV_META={"family":"field","phenomena":["temperature","wind"],"resource_types":["scalar_vector_grid"]}
SEMANTICS={"data_origin":"model","measurement_method":"nwp_model_data_file","observation_kind":"forecast"}

def requested_time(spec):
    if spec=={"mode":"latest"}:return None
    if not isinstance(spec,dict) or set(spec)!={"mode","at"} or spec["mode"]!="at_time" or not isinstance(spec["at"],str):raise TemperatureFieldUnavailable("temperature_unsupported_time")
    try:
        t=datetime.fromisoformat(spec["at"].replace("Z","+00:00"))
        if t.tzinfo is None:raise ValueError()
        return t.astimezone(timezone.utc)
    except ValueError as error:raise TemperatureFieldUnavailable("temperature_invalid_selected_time") from error

async def resolve_temperature_field(hass,msg):
    from .consumer_api import _runtime_state, _async_providers, _profile_for_request, _candidate_enabled
    response={"schema":"weather_router.consumer.temperature_field.v2","contract_version":2,"capability":CAPABILITY,"status":"unavailable","frame":None}
    def unavailable(code,**details):return {**response,"unavailable":{"code":code,**details}}
    if msg.get("contract_version")!=2 or msg.get("capability")!=CAPABILITY:return unavailable("temperature_unsupported_contract")
    try:
        target=requested_time(msg.get("time"));context=msg.get("context")
        if not isinstance(context,dict) or set(context)!={"bbox"}:return unavailable("temperature_invalid_context")
        plan_subset(context["bbox"])
    except WindFieldUnavailable as error:return unavailable(str(error))
    ready,state=_runtime_state(hass)
    if not ready:return unavailable("router_not_ready")
    if not state["router_enabled"]:return unavailable("router_disabled")
    if "weather" not in state["enabled_domains"]:return unavailable("domain_disabled")
    try:_,profile=_profile_for_request(hass,msg)
    except Exception as error:return unavailable(getattr(error,"code","profile_not_available"))
    def allows(profile,cap,meta):return profile_allows_capability(profile,{"public_capabilities":{cap:meta}},cap)
    ok,reason=allows(profile,CAPABILITY,META)
    if not ok:return unavailable(reason)
    ok,reason=profile_allows_candidate(profile,SEMANTICS)
    if not ok:return unavailable(reason)
    adv_allowed,adv_reason=allows(profile,ADVECTION,ADV_META);wanted=msg.get("include_advection") is True
    rejections=[]
    for provider in (await _async_providers(hass)).values():
        info=getattr(provider,"temperature_field_info",None);fetch=getattr(provider,"async_fetch_temperature_field",None)
        if not callable(info) or not callable(fetch) or info().get("capability")!=CAPABILITY:continue
        ok,reason=_candidate_enabled(state,provider,CAPABILITY)
        if not ok or not profile_allows_provider(profile,provider.id):rejections.append({"provider_id":provider.id,"code":reason or "profile_provider_filtered"});continue
        try:
            async with asyncio.timeout(62):frame=await fetch(hass,context["bbox"],include_advection=wanted and adv_allowed,target=target)
            current_ready,current=_runtime_state(hass);_,current_profile=_profile_for_request(hass,msg)
            if not current_ready or not _candidate_enabled(current,provider,CAPABILITY)[0] or not profile_allows_provider(current_profile,provider.id) or not allows(current_profile,CAPABILITY,META)[0] or not profile_allows_candidate(current_profile,SEMANTICS)[0]:return unavailable("temperature_policy_changed")
            current_adv,current_reason=allows(current_profile,ADVECTION,ADV_META)
            if not wanted or not adv_allowed or not current_adv:
                frame={**frame,"advection":{"status":"unavailable","capability":ADVECTION,"unavailable":{"code":(current_reason or adv_reason) if wanted else "not_requested"}}}
            return {**response,"status":"ready","frame":frame}
        except (WindFieldUnavailable,TimeoutError) as error:rejections.append({"provider_id":provider.id,"code":str(error) if isinstance(error,WindFieldUnavailable) else "temperature_source_timeout"})
    return unavailable(rejections[-1]["code"] if rejections else "temperature_field_not_supported",sources=rejections)

@websocket_api.websocket_command({vol.Required("type"):"weather_router/consumer/resolve_temperature_field",vol.Required("contract_version"):int,vol.Required("capability"):str,vol.Required("context"):dict,vol.Required("time"):dict,vol.Optional("include_advection",default=False):bool,vol.Optional("profile_id"):str,vol.Optional("consumer_id"):str})
@websocket_api.async_response
async def websocket_resolve_temperature_field(hass:HomeAssistant,connection,msg):
    from .diagnostic_center import record
    try:answer=await resolve_temperature_field(hass,msg)
    except Exception:answer={"schema":"weather_router.consumer.temperature_field.v2","contract_version":2,"capability":CAPABILITY,"status":"unavailable","frame":None,"unavailable":{"code":"temperature_field_unavailable"}}
    frame=answer.get("frame") or {}
    record(hass,category="consumer",outcome="success" if answer["status"]=="ready" else "unavailable",details={"capability":CAPABILITY,"code":answer.get("unavailable",{}).get("code"),"nodes":len(frame.get("grid",{}).get("valid_mask",[])),"advection_status":frame.get("advection",{}).get("status")})
    connection.send_result(msg["id"],answer)

def async_register(hass:HomeAssistant):websocket_api.async_register_command(hass,websocket_resolve_temperature_field)
