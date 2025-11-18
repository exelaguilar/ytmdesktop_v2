"""Async client for YTMDesktop v2 Companion Server API."""

import asyncio
import logging
from typing import Any, Dict, Optional

import aiohttp
import socketio
from homeassistant.core import HomeAssistant
from .const import API_BASE

_LOGGER = logging.getLogger(__name__)

# --- Custom Exceptions ---
class YTMDError(Exception):
    """Base exception for YTMDesktop errors."""
    pass

class YTMDConnectionError(YTMDError):
    """Raised when there is a connection or request error."""
    pass

class YTMDAuthError(YTMDError):
    """Raised when authorization fails."""
    pass
# -------------------------


class YTMDClient:
    def __init__(self, hass: HomeAssistant, host: str, port: int, token: Optional[str] = None) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        self.token = token
        self._session: Optional[aiohttp.ClientSession] = None
        self._sio: Optional[socketio.AsyncClient] = None
        self._connected = False
        self._state: Dict[str, Any] = {}
        self._listeners = []
        self._reconnect_task = None
        self._reconnect_delay = 1
        self._ws_url = f"http://{self.host}:{self.port}{API_BASE}/realtime"
        self._auth_headers = {"Authorization": self.token} if self.token else {}

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}{API_BASE}"

    def get_current_state(self) -> Dict[str, Any]:
        """Public method to retrieve the last known state."""
        return self._state

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    def _handle_request_error(self, resp: aiohttp.ClientResponse, url: str):
        """Handle non-200 HTTP responses."""
        if resp.status == 401:
            raise YTMDAuthError(f"Authorization failed for {url}. Check token.")
        if resp.status >= 400:
            raise YTMDConnectionError(f"Request failed to {url} with status {resp.status}.")

    async def async_request_code(self, app_name: str, app_version: str, app_id: str) -> Dict[str, Any]:
        """Request numeric authorization code from YTMDesktop."""
        await self._ensure_session()
        url = f"{self.base_url}/auth/requestcode"
        payload = {
            "appId": app_id,
            "appName": app_name,
            "appVersion": app_version
        }
        try:
            async with self._session.post(url, json=payload, timeout=10) as resp:
                self._handle_request_error(resp, url)
                return await resp.json()
        except aiohttp.ClientConnectorError as exc:
            raise YTMDConnectionError(f"Connection error to {url}: {exc}") from exc
        except asyncio.TimeoutError as exc:
            raise YTMDConnectionError(f"Timeout connecting to {url}: {exc}") from exc

    async def async_request_token(self, code: str, app_id: str) -> Dict[str, Any]:
        """Exchange numeric code for permanent authorization token."""
        await self._ensure_session()
        url = f"{self.base_url}/auth/request"
        payload = {
            "appId": app_id,
            "code": code
        }
        try:
            async with self._session.post(url, json=payload, timeout=10) as resp:
                self._handle_request_error(resp, url)
                return await resp.json()
        except aiohttp.ClientConnectorError as exc:
            raise YTMDConnectionError(f"Connection error to {url}: {exc}") from exc
        except asyncio.TimeoutError as exc:
            raise YTMDConnectionError(f"Timeout connecting to {url}: {exc}") from exc

    async def async_get_state(self) -> Dict[str, Any]:
        """Fetch the current state via HTTP."""
        await self._ensure_session()
        url = f"{self.base_url}/state"
        try:
            async with self._session.get(url, headers=self._auth_headers, timeout=10) as resp:
                self._handle_request_error(resp, url)
                data = await resp.json()
                self._state = data
                return data
        except aiohttp.ClientConnectorError as exc:
            raise YTMDConnectionError(f"Connection error to {url}: {exc}") from exc
        except asyncio.TimeoutError as exc:
            raise YTMDConnectionError(f"Timeout connecting to {url}: {exc}") from exc

    async def async_post_command(self, command: str, data: Optional[Any] = None) -> Dict[str, Any]:
        """Send a command to the YTMDesktop server."""
        await self._ensure_session()
        url = f"{self.base_url}/command"
        body = {"command": command}
        if data is not None:
            body["data"] = data
        try:
            async with self._session.post(url, json=body, headers=self._auth_headers, timeout=10) as resp:
                self._handle_request_error(resp, url)
                return await resp.json()
        except aiohttp.ClientConnectorError as exc:
            raise YTMDConnectionError(f"Connection error to {url}: {exc}") from exc
        except asyncio.TimeoutError as exc:
            raise YTMDConnectionError(f"Timeout connecting to {url}: {exc}") from exc


    async def async_connect(self):
        """Connect to the YTMDesktop WebSocket for realtime updates."""
        if self._connected:
            return
        await self._ensure_session()

        # Fetch initial state
        try:
            await self.async_get_state()
        except YTMDAuthError:
            raise
        except (YTMDConnectionError, Exception) as exc:
            _LOGGER.debug("Could not fetch initial state: %s. Proceeding with socket connection.", exc)

        self._sio = socketio.AsyncClient(logger=False, reconnection=False, engineio_logger=False)

        @self._sio.event
        async def connect():
            _LOGGER.info("Connected to YTMD realtime socket")
            self._reconnect_delay = 1
            self._connected = True

        @self._sio.event
        async def disconnect():
            _LOGGER.warning("Disconnected from YTMD realtime socket")
            self._connected = False
            self._schedule_reconnect()

        @self._sio.on("state-update")
        async def on_state_update(data):
            self._state = data
            for cb in list(self._listeners):
                try:
                    cb(data)
                except Exception:
                    _LOGGER.exception("Listener callback failed")

        auth = {"token": self.token} if self.token else {}
        try:
            await self._sio.connect(self._ws_url, transports=["websocket"], auth=auth, namespaces=["/"])
        except Exception as exc:
            if not self._connected:
                _LOGGER.warning("Initial socket connection failed: %s", exc)
                await self.async_disconnect()
                raise YTMDConnectionError(f"Initial connection to socket failed: {exc}") from exc
            else:
                _LOGGER.warning("Socket connect failed: %s", exc)
                self._schedule_reconnect()


    def add_listener(self, callback):
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback):
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _schedule_reconnect(self):
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        await asyncio.sleep(self._reconnect_delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, 300)
        try:
            await self.async_connect()
        except Exception as exc:
            _LOGGER.debug("Reconnect attempt failed: %s", exc)
            self._schedule_reconnect()

    async def async_disconnect(self):
        """Disconnect the client and close the session."""
        if self._sio:
            try:
                await self._sio.disconnect()
            except Exception:
                _LOGGER.exception("Error disconnecting socket")
        
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        
        if self._session and not self._session.closed:
            await self._session.close()
            
        self._connected = False
        self._sio = None
        self._session = None