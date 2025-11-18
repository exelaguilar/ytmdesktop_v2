"""YTMDesktop v2 Home Assistant integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .api_client import YTMDClient
import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["media_player"]

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data.get("host")
    port = entry.data.get("port")
    token = entry.data.get("token")
    app_id = entry.data.get("app_id")
    app_name = entry.data.get("app_name")
    app_version = entry.data.get("app_version")

    client = YTMDClient(hass, host, port, token)
    hass.data[DOMAIN][entry.entry_id] = client

    await client.async_connect()

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    # listen for unload
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True

async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # currently no options but keep placeholder
    _LOGGER.debug("Options updated for %s", entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client: YTMDClient = hass.data[DOMAIN].get(entry.entry_id)
    if client:
        await client.async_disconnect()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
