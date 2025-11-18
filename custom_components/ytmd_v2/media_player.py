import logging
from typing import Any, Dict, Optional, Callable
from datetime import timedelta

from homeassistant.components.media_player import (
    MediaPlayerEntity, 
    MediaPlayerEntityFeature, 
    MediaPlayerState,
    MediaType
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util.dt import utcnow

from .const import DOMAIN
from .api_client import YTMDClient

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL_PROGRESS = timedelta(seconds=1)

def _player_state_from_data(data) -> MediaPlayerState:
    player = data.get("player") or {}
    track_state = player.get("trackState")
    
    if track_state == 1:
        return MediaPlayerState.PLAYING
    if track_state == 2:
        return MediaPlayerState.PAUSED
        
    if data.get("video"):
        return MediaPlayerState.IDLE
        
    return MediaPlayerState.IDLE

def _get_thumbnail_url(thumbnails: list) -> Optional[str]:
    if not thumbnails or not isinstance(thumbnails, list):
        return None
        
    last_thumbnail = thumbnails[-1]
    return last_thumbnail.get("url") if last_thumbnail else None

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: YTMDClient = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([YTMDMediaPlayer(hass, config_entry.entry_id, client)])

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
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.VOLUME_MUTE
    )
    _attr_device_class = "speaker"

    def __init__(self, hass: HomeAssistant, entry_id: str, client: YTMDClient):
        self.hass = hass
        self._client = client

        self._attr_name = f"YTMDesktop ({client.host})"
        self._attr_unique_id = entry_id
        
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{client.host}:{client.port}")},
            name=f"YTMDesktop Companion ({client.host})",
            manufacturer="YTMDesktop",
            model="Companion Server v2",
        )

        self._state: Optional[MediaPlayerState] = None
        self._position = 0.0
        self._duration = 0.0
        self._media_title = None
        self._media_artist = None
        self._media_album = None
        self._shuffle = None
        self._repeat = None
        self._like_status = None
        self._current_video_id = None
        
        self._attr_volume_level = None
        self._attr_is_volume_muted = None
        self._attr_media_image_url = None
        self._attr_media_position_updated_at = None

        self._unsub_progress: Optional[Callable[[], None]] = None

    async def async_added_to_hass(self):
        self._client.add_listener(self._on_state_update)
        self._start_progress_timer()
        
    async def async_will_remove_from_hass(self):
        self._client.remove_listener(self._on_state_update)
        if self._unsub_progress:
            self._unsub_progress()
            self._unsub_progress = None

    def _start_progress_timer(self):
        if self._unsub_progress is None:
            self._unsub_progress = async_track_time_interval(
                self.hass, self._update_progress, SCAN_INTERVAL_PROGRESS
            )

    @callback
    def _update_progress(self, now):
        if (
            self._state == MediaPlayerState.PLAYING
            and self.available
            and self._position is not None
            and self._duration > 0
        ):
            if self._attr_media_position_updated_at:
                elapsed = (utcnow() - self._attr_media_position_updated_at).total_seconds()
                new_position = self._position + elapsed
            else:
                new_position = self._position + SCAN_INTERVAL_PROGRESS.total_seconds()
            
            if new_position >= self._duration:
                new_position = self._duration
                
            self._position = new_position
            
            self.schedule_update_ha_state()

    @callback
    def _on_state_update(self, data: Dict[str, Any]):
        if not data:
            _LOGGER.debug("Received empty state data. Forcing HA update.")
            self._state = MediaPlayerState.IDLE
            self.schedule_update_ha_state()
            return

        try:
            player = data.get("player") or {}
            video = data.get("video") or {}
            queue = player.get("queue") or {}
            
            selected_item = next((item for item in queue.get("items", []) if item.get("selected")), None)

            self._state = _player_state_from_data(data)
            
            self._attr_volume_level = (player.get("volume") / 100) if isinstance(player.get("volume"), (int, float)) else None
            self._attr_is_volume_muted = player.get("muted")
            self._shuffle = player.get("shuffle")
            self._repeat = queue.get("repeatMode")

            new_position = player.get("videoProgress")
            if new_position is not None:
                self._position = new_position
                self._attr_media_position_updated_at = utcnow()
                
            self._duration = video.get("durationSeconds") or 0.0

            new_video_id = video.get("id")
            
            if new_video_id:
                self._current_video_id = new_video_id
                self._media_title = video.get("title")
                self._media_artist = video.get("author")
                self._media_album = video.get("album")
                self._like_status = video.get("likeStatus")
                
                self._attr_media_image_url = _get_thumbnail_url(video.get("thumbnails"))

                if not self._media_artist and selected_item:
                    self._media_artist = selected_item.get("author")
                
                if not self._attr_media_image_url and selected_item:
                    self._attr_media_image_url = _get_thumbnail_url(selected_item.get("thumbnails"))
            else:
                self._current_video_id = None
                self._media_title = None
                self._media_artist = None
                self._media_album = None
                self._attr_media_image_url = None
                self._like_status = None
                
            self.schedule_update_ha_state()
            
        except Exception:
            _LOGGER.exception("Failed to process state-update callback.")

    @property
    def available(self) -> bool:
        return self._client.is_connected
        
    @property
    def state(self): return self._state
    @property
    def volume_level(self) -> Optional[float]: return self._attr_volume_level
    @property
    def media_position(self) -> Optional[float]: 
        return self._position
        
    @property
    def media_duration(self) -> Optional[float]: return self._duration
    @property
    def media_title(self) -> Optional[str]: return self._media_title
    @property
    def media_artist(self) -> Optional[str]: return self._media_artist
    @property
    def media_album_name(self) -> Optional[str]: return self._media_album
    
    @property
    def media_content_type(self) -> str:
        return MediaType.MUSIC
        
    @property
    def media_image_url(self) -> Optional[str]: return self._attr_media_image_url
    @property
    def device_info(self) -> DeviceInfo: return self._device_info
    @property
    def extra_state_attributes(self) -> dict:
        return {"like_status": self._like_status, "shuffle": self._shuffle, "repeat": self._repeat}

    async def async_media_play(self): await self._client.async_post_command("play")
    async def async_media_pause(self): await self._client.async_post_command("pause")
    async def async_media_stop(self): await self._client.async_post_command("pause")
    async def async_media_next_track(self): await self._client.async_post_command("next")
    async def async_media_previous_track(self): await self._client.async_post_command("previous")
    async def async_set_volume_level(self, volume: float): await self._client.async_post_command("setVolume", int(volume*100))
    async def async_media_seek(self, position: float): await self._client.async_post_command("seekTo", int(position))
    async def async_set_shuffle(self, shuffle: bool): await self._client.async_post_command("shuffle")
    async def async_set_repeat(self, repeat_mode: int): await self._client.async_post_command("repeatMode", repeat_mode)
    async def async_volume_mute(self, mute: bool): await self._client.async_post_command("mute" if mute else "unmute")
    async def async_change_video(self, video_id: str, playlist_id: Optional[str]=None):
        data = {"videoId": video_id}
        if playlist_id: data["playlistId"] = playlist_id
        await self._client.async_post_command("changeVideo", data)
    async def async_toggle_like(self, like: bool):
        if like: await self._client.async_post_command("toggleLike")
        else: await self._client.async_post_command("toggleDislike")