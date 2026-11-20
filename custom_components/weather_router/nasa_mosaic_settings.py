"""Admin-only switch, default off; unrelated to OPERA scientific admission."""
import voluptuous as vol
from homeassistant.components import websocket_api
from .const import DOMAIN
from .nasa_mosaic import OPTION, PARALLEL_OPTION, configured_parallel

def validate_parallel(value):
    if type(value) is not int or not 2<=value<=32:raise vol.Invalid("NASA parallelism must be an integer from 2 to 32")
    return value

@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required('type'):'weather_router/precipitation/settings',vol.Optional('nasa_imerg_complement'):bool,vol.Optional('nasa_max_parallel_downloads'):validate_parallel})
@websocket_api.async_response
async def settings(hass,connection,msg):
    entries=hass.config_entries.async_entries(DOMAIN)
    if len(entries)!=1:
        connection.send_error(msg['id'],'not_configured','WeatherRouter not configured');return
    entry=entries[0]
    if OPTION in msg or PARALLEL_OPTION in msg:
        policy_changed=OPTION in msg and entry.options.get(OPTION,False) is not msg[OPTION]
        changed={key:msg[key] for key in (OPTION,PARALLEL_OPTION) if key in msg}
        hass.config_entries.async_update_entry(entry,options={**entry.options,**changed,"nasa_transport_revision":entry.options.get("nasa_transport_revision",0)+1})
        enabled=entry.options.get(OPTION,False) is True
        hass.data.setdefault(DOMAIN,{})["nasa_mosaic_status"]={"enabled":enabled,"metadata_state":"not_started" if enabled else "disabled"}
        if not enabled:
            runtime=hass.data.get(DOMAIN,{})
            job=runtime.pop('nasa_metadata_preparation',None)
            if job:job.close()
        hass.bus.async_fire('weather_router_routing_changed',{'precipitation_policy_changed':policy_changed,'nasa_transport_changed':PARALLEL_OPTION in msg,OPTION:enabled,'nasa_transport_policy':{'max_parallel_downloads':configured_parallel(entry.options),'settings_revision':entry.options['nasa_transport_revision']}})
    connection.send_result(msg['id'],{'schema':'weather_router.precipitation.settings.v1',OPTION:entry.options.get(OPTION,False) is True,PARALLEL_OPTION:configured_parallel(entry.options),'max_active_tiles':48,'padding_factor':1.3})

def async_register(hass):websocket_api.async_register_command(hass,settings)
