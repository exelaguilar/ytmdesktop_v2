import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import ConfigEntryNotReady
from .api_client import YTMDConnectionError, YTMDAuthError
from .const import DOMAIN
from .api_client import YTMDClient

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["media_player"]

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data.get("host")
    port = entry.data.get("port")
    token = entry.data.get("token")
    
    client = YTMDClient(hass, host, port, token)
    hass.data[DOMAIN][entry.entry_id] = client

    try:
        await client.async_connect()
        
    except YTMDAuthError as e:
        _LOGGER.error("Authorization failed for YTMDesktop client: %s", e)
        return False
        
    except YTMDConnectionError:
        _LOGGER.warning(
            "Initial connection failed for %s:%s. Client will automatically retry connection.", 
            host, port
        )
        
    except Exception as e:
        _LOGGER.exception("An unexpected error occurred during YTMDesktop client connection.")
        raise ConfigEntryNotReady(f"Unexpected connection error: {e}") from e

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    
    return True

async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry):
    _LOGGER.debug("Options updated for %s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client: YTMDClient = hass.data[DOMAIN].get(entry.entry_id)
    if client:
        await client.async_disconnect()
        hass.data[DOMAIN].pop(entry.entry_id, None)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        
    return unload_ok