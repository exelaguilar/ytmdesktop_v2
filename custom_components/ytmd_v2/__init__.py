"""YTMDesktop v2 Home Assistant integration."""
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
    """Set up the integration."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    host = entry.data.get("host")
    port = entry.data.get("port")
    token = entry.data.get("token")
    
    client = YTMDClient(hass, host, port, token)
    hass.data[DOMAIN][entry.entry_id] = client

    try:
        await client.async_connect()
    except (YTMDConnectionError, YTMDAuthError) as e:
        _LOGGER.error("Failed to connect or authorize YTMDesktop client: %s", e)
        raise ConfigEntryNotReady(f"Failed to connect to YTMDesktop at {host}:{port}. Check connection/auth.") from e
    except Exception as e:
        _LOGGER.exception("An unexpected error occurred during YTMDesktop client connection.")
        raise ConfigEntryNotReady(f"Unexpected connection error: {e}") from e

    # FIX for HA 2025.11+: Use async_forward_entry_setups on hass.config_entries
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    
    return True

async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    _LOGGER.debug("Options updated for %s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    client = hass.data[DOMAIN].get(entry.entry_id)
    
    # Use async_unload_platforms on hass.config_entries
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if client:
        await client.async_disconnect()

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        
    return unload_ok