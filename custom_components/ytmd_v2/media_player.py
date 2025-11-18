"""Media player entity for YTMDesktop v2."""
import logging
from typing import Any, Dict, Optional
from homeassistant.components.media_player import MediaPlayerEntity, MediaPlayerEntityFeature
from homeassistant.const import STATE_PLAYING, STATE_PAUSED, STATE_IDLE
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN
_LOGGER = logging.getLogger(__name__)

def _player_state_from_data(data) -> str:
    player = data.get("player") or {}
    track_state = player.get("trackState")
    if track_state == 1:
        return STATE_PLAYING
    if track_state == 0:
        return STATE_PAUSED
    return STATE_IDLE

class YTMDMediaPlayer(MediaPlayerEntity):
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.SEEK
        | MediaPlayerEntityFeature.SHUFFLE_SET
        | MediaPlayerEntityFeature.REPEAT_SET
    )
    def __init__(self, hass, entry_id, client):
        self.hass = hass
        self._entry_id = entry_id
        self._client = client
        self._state = None
        self._volume = None
        self._position = None
        self._media_title = None
        self._media_artist = None
        self._media_album = None
        self._shuffle = None
        self._repeat = None
        
        self._attr_name = f"YTMDesktop ({client.host})"
        self._attr_unique_id = entry_id # Added unique ID
        self._device_info = DeviceInfo(identifiers={(DOMAIN, f"{client.host}:{client.port}")})
        
    async def async_added_to_hass(self):
        self._client.add_listener(self._on_state_update)
        # Use public getter for initial state
        initial_state = self._client.get_current_state()
        if initial_state:
            self._on_state_update(initial_state)
            
    async def async_will_remove_from_hass(self):
        self._client.remove_listener(self._on_state_update)
        
    def _on_state_update(self, data: Dict[str, Any]):
        try:
            player = data.get("player", {})
            queue = player.get("queue", {})
            position = data.get("videoProgress") or player.get("progress")
            volume = player.get("volume")
            self._state = _player_state_from_data(data)
            self._volume = (volume / 100) if isinstance(volume, (int, float)) else None
            self._position = position or 0
            items = queue.get("items") if isinstance(queue, dict) else None
            cur = None
            if items and isinstance(items, list):
                for it in items:
                    if it.get("playing"):
                        cur = it
                        break
                if cur is None and len(items) > 0:
                    cur = items[0]
            if cur:
                self._media_title = cur.get("title")
                self._media_artist = ", ".join(cur.get("artists", [])) if cur.get("artists") else cur.get("artistsNames") or None
                self._media_album = cur.get("album", {}).get("name") if cur.get("album") else None
            else:
                self._media_title = None
                self._media_artist = None
                self._media_album = None
            self._shuffle = player.get("shuffle")
            self._repeat = player.get("repeatMode")
            self.schedule_update_ha_state()
        except Exception:
            _LOGGER.exception("Failed to update from state-update")
            
    @property
    def state(self):
        return self._state
    @property
    def volume_level(self) -> Optional[float]:
        return self._volume
    @property
    def media_position(self) -> Optional[float]:
        return self._position
    @property
    def media_title(self) -> Optional[str]:
        return self._media_title
    @property
    def media_artist(self) -> Optional[str]:
        return self._media_artist
    @property
    def media_album_name(self) -> Optional[str]:
        return self._media_album
    @property
    def device_info(self) -> DeviceInfo:
        return self._device_info
        
    async def async_media_play(self) -> None:
        await self._client.async_post_command("play")
    async def async_media_pause(self) -> None:
        await self._client.async_post_command("pause")
    async def async_media_next_track(self) -> None:
        await self._client.async_post_command("next")
    async def async_media_previous_track(self) -> None:
        await self._client.async_post_command("previous")
    async def async_set_volume_level(self, volume: float) -> None:
        await self._client.async_post_command("setVolume", int(volume * 100))
    async def async_seek(self, position: float) -> None:
        await self._client.async_post_command("seek", int(position))
    async def async_set_shuffle(self, shuffle: bool) -> None:
        await self._client.async_post_command("shuffle", shuffle)
    async def async_set_repeat(self, repeat_mode: int) -> None:
        await self._client.async_post_command("repeatMode", repeat_mode)