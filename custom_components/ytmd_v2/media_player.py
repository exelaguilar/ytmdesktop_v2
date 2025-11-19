"""YTMDesktop v2 Home Assistant media_player entity (HA 2024.12+)."""

import logging
from typing import Any, Dict, Optional, Callable
from datetime import timedelta

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.components.media_player.const import RepeatMode
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


def _player_state_from_data(data: Dict[str, Any]) -> MediaPlayerState:
    player = data.get("player") or {}
    track_state = player.get("trackState")

    if track_state == 1:
        return MediaPlayerState.PLAYING
    if track_state == 2:
        return MediaPlayerState.PAUSED

    if data.get("video"):
        return MediaPlayerState.IDLE

    return MediaPlayerState.IDLE


def _get_thumbnail_url(thumbnails: Optional[list]) -> Optional[str]:
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
    async_add_entities([YTMDMediaPlayer(hass, config_entry.entry_id, client)], True)


class YTMDMediaPlayer(MediaPlayerEntity):
    """YTMDesktop Companion media player (modern HA API)."""

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

    def __init__(self, hass: HomeAssistant, entry_id: str, client: YTMDClient) -> None:
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

        # Core state
        self._state: MediaPlayerState = MediaPlayerState.IDLE

        # Media metadata + playback tracking
        self._position: float = 0.0
        self._duration: float = 0.0
        self._media_title: Optional[str] = None
        self._media_artist: Optional[str] = None
        self._media_album: Optional[str] = None
        self._shuffle: Optional[bool] = None
        self._repeat: Optional[int] = None
        self._like_status: Optional[str] = None
        self._current_video_id: Optional[str] = None

        # HA attributes
        self._attr_volume_level: Optional[float] = None
        self._attr_is_volume_muted: Optional[bool] = None
        self._attr_media_image_url: Optional[str] = None
        self._attr_media_position_updated_at: Optional[Any] = None

        # Progress update interval unsubscribe
        self._unsub_progress: Optional[Callable[[], None]] = None
        self._pending_write: bool = False

    async def async_added_to_hass(self) -> None:
        self._client.add_listener(self._on_state_update)
        self._start_progress_timer()

    async def async_will_remove_from_hass(self) -> None:
        self._client.remove_listener(self._on_state_update)
        if self._unsub_progress:
            self._unsub_progress()
            self._unsub_progress = None

    def _start_progress_timer(self) -> None:
        if self._unsub_progress is None:
            self._unsub_progress = async_track_time_interval(
                self.hass, self._update_progress, SCAN_INTERVAL_PROGRESS
            )

    @callback
    def _update_progress(self, now) -> None:
        """Increment the position while playing to keep the UI scrubber moving."""
        if (
            self._state == MediaPlayerState.PLAYING
            and self.available
            and self._position is not None
            and self._duration > 0
        ):
            elapsed = (
                (utcnow() - self._attr_media_position_updated_at).total_seconds()
                if self._attr_media_position_updated_at
                else SCAN_INTERVAL_PROGRESS.total_seconds()
            )
            new_position = self._position + elapsed
            if new_position >= self._duration:
                new_position = self._duration

            if abs(new_position - self._position) >= 0.5:
                self._position = new_position
                self._attr_media_position_updated_at = utcnow()
                if not self._pending_write:
                    self._pending_write = True
                    self.hass.loop.call_soon_threadsafe(self._write_state)

    @callback
    def _write_state(self) -> None:
        """Write HA state and clear pending flag."""
        self._pending_write = False
        try:
            self.async_write_ha_state()
        except Exception:
            self.schedule_update_ha_state()

    @callback
    def _on_state_update(self, data: Dict[str, Any]) -> None:
        """Process incoming state updates from YTMD client."""
        if not data:
            _LOGGER.debug("Received empty state data. Forcing HA update.")
            self._state = MediaPlayerState.IDLE
            self._write_state()
            return

        try:
            player = data.get("player") or {}
            video = data.get("video") or {}
            queue = player.get("queue") or {}
            selected_item = next(
                (item for item in queue.get("items", []) if item.get("selected")), None
            )

            changed = False

            # State
            new_state = _player_state_from_data(data)
            if new_state != self._state:
                self._state = new_state
                changed = True

            # Volume & mute
            volume = player.get("volume")
            new_volume_level = (volume / 100) if isinstance(volume, (int, float)) else None
            if new_volume_level != self._attr_volume_level:
                self._attr_volume_level = new_volume_level
                changed = True

            muted = player.get("muted")
            if muted != self._attr_is_volume_muted:
                self._attr_is_volume_muted = muted
                changed = True

            # Shuffle
            shuffle = player.get("shuffle")
            if shuffle != self._shuffle:
                self._shuffle = shuffle
                changed = True

            # Repeat
            repeat_mode = queue.get("repeatMode")
            if repeat_mode != self._repeat:
                self._repeat = repeat_mode
                changed = True

            # Position
            new_position = player.get("videoProgress")
            if new_position is not None and new_position != self._position:
                self._position = float(new_position)
                self._attr_media_position_updated_at = utcnow()
                changed = True

            # Duration
            new_duration = video.get("durationSeconds") or 0.0
            if float(new_duration) != float(self._duration):
                self._duration = float(new_duration)
                changed = True

            # Video metadata
            new_video_id = video.get("id")
            if new_video_id:
                if new_video_id != self._current_video_id:
                    self._current_video_id = new_video_id
                    changed = True

                title = video.get("title")
                author = video.get("author") or (selected_item.get("author") if selected_item else None)
                album = video.get("album")
                like_status = video.get("likeStatus")
                thumb = _get_thumbnail_url(video.get("thumbnails")) or (
                    _get_thumbnail_url(selected_item.get("thumbnails")) if selected_item else None
                )

                for attr, value in [
                    ("_media_title", title),
                    ("_media_artist", author),
                    ("_media_album", album),
                    ("_like_status", like_status),
                    ("_attr_media_image_url", thumb),
                ]:
                    if getattr(self, attr) != value:
                        setattr(self, attr, value)
                        changed = True
            else:
                for attr in ["_current_video_id", "_media_title", "_media_artist", "_media_album", "_like_status", "_attr_media_image_url"]:
                    if getattr(self, attr) is not None:
                        setattr(self, attr, None)
                        changed = True

            if changed and not self._pending_write:
                self._pending_write = True
                self.hass.loop.call_soon_threadsafe(self._write_state)

        except Exception:
            _LOGGER.exception("Failed to process state-update callback.")

    # --- Properties ---
    @property
    def available(self) -> bool:
        return self._client.is_connected

    @property
    def state(self) -> MediaPlayerState:
        return self._state

    @property
    def volume_level(self) -> Optional[float]:
        return self._attr_volume_level

    @property
    def is_volume_muted(self) -> Optional[bool]:
        return self._attr_is_volume_muted

    @property
    def media_position(self) -> Optional[float]:
        return self._position

    @property
    def media_duration(self) -> Optional[float]:
        return self._duration

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
    def media_content_type(self) -> MediaType:
        return MediaType.MUSIC

    @property
    def media_image_url(self) -> Optional[str]:
        return self._attr_media_image_url

    @property
    def device_info(self) -> DeviceInfo:
        return self._device_info

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            "like_status": self._like_status,
            "shuffle": self._shuffle,
            "repeat": self._repeat,
            "current_video_id": self._current_video_id,
        }

    # --- Control commands ---
    async def async_media_play(self) -> None:
        await self._safe_command("play")

    async def async_media_pause(self) -> None:
        await self._safe_command("pause")

    async def async_media_stop(self) -> None:
        await self._safe_command("pause")

    async def async_media_next_track(self) -> None:
        await self._safe_command("next")

    async def async_media_previous_track(self) -> None:
        await self._safe_command("previous")

    async def async_set_volume_level(self, volume: float) -> None:
        await self._safe_command("setVolume", int(volume * 100))

    async def async_volume_mute(self, is_volume_muted: bool) -> None:
        """Mute/unmute respecting YTMD API."""
        if self._attr_is_volume_muted is None:
            return

        if is_volume_muted and not self._attr_is_volume_muted:
            await self._safe_command("mute")
        elif not is_volume_muted and self._attr_is_volume_muted:
            await self._safe_command("unmute")

    async def async_media_seek(self, position: float) -> None:
        await self._safe_command("seekTo", int(position))

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Set repeat mode correctly for YTMD v2 API."""
        if repeat == RepeatMode.OFF:
            mode = 0
        elif repeat == RepeatMode.ALL:
            mode = 1
        elif repeat == RepeatMode.ONE:
            mode = 2
        else:
            return
        await self._safe_command("repeatMode", mode)

    async def async_set_shuffle(self, shuffle: bool) -> None:
        await self._safe_command("shuffle")

    async def async_toggle_like(self, like: bool) -> None:
        await self._safe_command("toggleLike" if like else "toggleDislike")

    async def async_change_video(self, video_id: str, playlist_id: Optional[str] = None) -> None:
        data: Dict[str, Any] = {}
        if video_id:
            data["videoId"] = video_id
        if playlist_id:
            data["playlistId"] = playlist_id
        await self._safe_command("changeVideo", data)

    async def _safe_command(self, command: str, data: Any = None) -> None:
        """Send command to YTMD backend safely."""
        try:
            if data is None or data == {}:
                await self._client.async_post_command(command)
            else:
                await self._client.async_post_command(command, data)
        except Exception:
            _LOGGER.exception("Failed to send command '%s' to YTMD backend", command)