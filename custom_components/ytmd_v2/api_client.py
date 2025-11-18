"""Async client for YTMDesktop v2 Companion Server API."""

import asyncio
import logging
from typing import Any, Dict, Optional

import aiohttp
import socketio
from homeassistant.core import HomeAssistant
from .const import API_BASE

_LOGGER = logging.getLogger(__name__)

class YTMDClient:
    def __init__(self, hass: HomeAssistant, host: str, port: int, token: Optional[str]) -> None:
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

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}{API_BASE}"

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def async_request_code(self, app_name="HA YTMDesktop Integration", app_version="0.1") -> Dict[str, Any]:
        await self._ensure_session()
        url = f"{self.base_url}/auth/requestcode"
        payload = {"appName": app_name, "appVersion": app_version}
        async with self._session.post(url, json=payload, timeout=10) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def async_request_token(self, code: str, app_name="HA YTMDesktop Integration", app_version="0.1") -> Dict[str, Any]:
        await self._ensure_session()
        url = f"{self.base_url}/auth/request"
        payload = {"code": code, "appName": app_name, "appVersion": app_version}
        async with self._session.post(url, json=payload, timeout=10) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def async_get_state(self) -> Dict[str, Any]:
        await self._ensure_session()
        url = f"{self.base_url}/state"
        headers = {}
        if self.token:
            headers["Authorization"] = self.token
        async with self._session.get(url, headers=headers, timeout=10) as resp:
            resp.raise_for_status()
            data = await resp.json()
            self._state = data
            return data

    async def async_post_command(self, command: str, data: Optional[Any] = None) -> Dict[str, Any]:
        await self._ensure_session()
        url = f"{self.base_url}/command"
        headers = {}
        if self.token:
            headers["Authorization"] = self.token
        body = {"command": command}
        if data is not None:
            body["data"] = data
        async with self._session.post(url, json=body, headers=headers, timeout=10) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def async_connect(self):
        if self._connected:
            return
        await self._ensure_session()

        # Fetch initial state
        try:
            await self.async_get_state()
        except Exception as exc:
            _LOGGER.debug("Could not fetch initial state: %s", exc)

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

        ws_url = f"http://{self.host}:{self.port}{API_BASE}/realtime"
        auth = {"token": self.token} if self.token else {}
        try:
            await self._sio.connect(ws_url, transports=["websocket"], auth=auth, namespaces=["/"])
        except Exception as exc:
            _LOGGER.warning("Socket connect failed: %s", exc)
            self._schedule_reconnect()
            return

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
        if self._sio:
            try:
                await self._sio.disconnect()
            except Exception:
                _LOGGER.exception("Error disconnecting socket")
        if self._session:
            await self._session.close()
        self._connected = False
