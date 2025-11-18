"""YTMDesktop v2 Home Assistant integration."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import ConfigEntryNotReady
# Import exceptions from api_client for specific handling
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
    
    # app_name and app_version are not strictly needed here, but kept for context if necessary
    # app_name = entry.data.get("app_name")
    # app_version = entry.data.get("app_version")
    
    client = YTMDClient(hass, host, port, token)
    hass.data[DOMAIN][entry.entry_id] = client

    try:
        await client.async_connect()
    except (YTMDConnectionError, YTMDAuthError) as e:
        _LOGGER.error("Failed to connect or authorize YTMDesktop client: %s", e)
        # Raise ConfigEntryNotReady for recoverable errors (network, host down)
        raise ConfigEntryNotReady(f"Failed to connect to YTMDesktop at {host}:{port}. Check connection/auth.") from e
    except Exception as e:
        _LOGGER.exception("An unexpected error occurred during YTMDesktop client connection.")
        raise ConfigEntryNotReady(f"Unexpected connection error: {e}") from e

    # Setup platforms after successful connection
    await hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    
    # Listener for options updates
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    
    return True

async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    _LOGGER.debug("Options updated for %s", entry.entry_id)
    # Reload entry to apply new options (if implemented)
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    client = hass.data[DOMAIN].get(entry.entry_id)
    
    # Unload platforms first
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if client:
        # Disconnect client gracefully
        await client.async_disconnect()

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        
    return unload_ok