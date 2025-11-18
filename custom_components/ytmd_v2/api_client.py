import asyncio 
import logging
from typing import Any, Dict, Optional, Callable

import aiohttp
import socketio
from homeassistant.core import HomeAssistant 
from .const import API_BASE

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.INFO) 

class YTMDError(Exception):
    pass
class YTMDConnectionError(YTMDError):
    pass
class YTMDAuthError(YTMDError):
    pass

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
        self._listeners: list[Callable[[Dict[str, Any]], None]] = [] 
        self._reconnect_task = None
        self._reconnect_delay = 1
        
        self._ws_url = f"ws://{self.host}:{self.port}"
        self._namespace = f"{API_BASE}/realtime"
        
        self._auth_headers = {"Authorization": self.token} if self.token else {}
        
        self._sio_logger = logging.getLogger(f"{__name__}.socketio")
        self._sio_logger.setLevel(logging.INFO) 
        self._engineio_logger = logging.getLogger("engineio")
        self._engineio_logger.setLevel(logging.INFO)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}{API_BASE}"

    def get_current_state(self) -> Dict[str, Any]:
        return self._state
    
    @property
    def is_connected(self) -> bool:
        return self._connected and (self._sio and self._sio.connected)

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    def _handle_request_error(self, resp: aiohttp.ClientResponse, url: str):
        if resp.status == 401:
            raise YTMDAuthError(f"Authorization failed for {url}. Check token.")
        if resp.status == 429: 
            raise YTMDConnectionError(f"Request failed to {url} with status 429 (Too Many Requests).")
        if resp.status >= 400:
            raise YTMDConnectionError(f"Request failed to {url} with status {resp.status}.")

    async def async_request_code(
        self,
        app_name: str,
        app_version: str,
        app_id: str
    ) -> Dict[str, Any]:
        await self._ensure_session()
        url = f"http://{self.host}:{self.port}{API_BASE}/auth/requestcode"
        
        body = {
            "appId": app_id,
            "appName": app_name,
            "appVersion": app_version,
        }
        
        try:
            async with self._session.post(url, json=body, timeout=10) as resp:
                self._handle_request_error(resp, url)
                return await resp.json()
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as exc:
            _LOGGER.error("Connection/Timeout error while requesting code: %s", exc)
            raise YTMDConnectionError(f"Connection error to {url}: {exc}") from exc

    async def async_request_token(self, code: str, app_id: str) -> Dict[str, Any]:
        await self._ensure_session()
        url = f"http://{self.host}:{self.port}{API_BASE}/auth/request"
        body = {"code": code, "appId": app_id}
        
        try:
            async with self._session.post(url, json=body, timeout=35) as resp: 
                self._handle_request_error(resp, url)
                return await resp.json()
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as exc:
            _LOGGER.error("Connection/Timeout error while requesting token: %s", exc)
            raise YTMDConnectionError(f"Connection error to {url}: {exc}") from exc
            
    async def async_get_state(self) -> Dict[str, Any]:
        await self._ensure_session()
        url = f"http://{self.host}:{self.port}{API_BASE}/state"
        try:
            async with self._session.get(url, headers=self._auth_headers, timeout=10) as resp:
                self._handle_request_error(resp, url)
                return await resp.json()
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as exc:
            raise YTMDConnectionError(f"Connection error to {url}: {exc}") from exc
            
    async def async_post_command(self, command: str, data: Optional[Any] = None) -> Dict[str, Any]:
        await self._ensure_session()
        url = f"http://{self.host}:{self.port}{API_BASE}/command"
        body = {"command": command}
        if data is not None:
            body["data"] = data
        
        try:
            async with self._session.post(url, json=body, headers=self._auth_headers, timeout=10) as resp:
                self._handle_request_error(resp, url)
                if resp.status == 204:
                    return {"status": "success"}
                
                return await resp.json()
        except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as exc:
            _LOGGER.error("Connection/Timeout error while sending command %s: %s", command, exc)
            raise YTMDConnectionError(f"Connection error to {url}: {exc}") from exc

    async def async_connect(self):
        if self._sio and self._sio.connected:
            self._connected = True
            if self._reconnect_task and not self._reconnect_task.done():
                self._reconnect_task.cancel()
            return

        await self._ensure_session()
        
        if self._sio:
            try:
                await self._sio.disconnect()
            except Exception:
                pass
            self._sio = None
        
        self._sio = socketio.AsyncClient(
            logger=self._sio_logger, 
            reconnection=False, 
            engineio_logger=self._engineio_logger,
        )

        @self._sio.event
        async def connect():
            _LOGGER.warning("Socket.IO client connected successfully to namespace %s.", self._namespace)
            self._reconnect_delay = 1
            self._connected = True
            await self._force_state_update_to_listeners(use_http_if_available=True)

        @self._sio.event
        async def disconnect():
            _LOGGER.warning("Socket.IO client disconnected. Scheduling reconnect.")
            self._connected = False
            self._schedule_reconnect()
            await self._notify_listeners_of_disconnect() 

        @self._sio.event
        async def connect_error(data):
            _LOGGER.error("Socket.IO connection error: %s", data)
            self._connected = False
            self._schedule_reconnect()
            await self._notify_listeners_of_disconnect()

        @self._sio.on("state-update", namespace=self._namespace)
        async def on_state_update(data):
            self._state = data
            await self._push_state_to_listeners(data)

        auth = {"token": self.token} if self.token else {}
        
        await self._force_state_update_to_listeners(use_http_if_available=True)
            
        try:
            await self._sio.connect(
                self._ws_url, 
                transports=["websocket"], 
                auth=auth, 
                namespaces=[self._namespace]
            )
            
            if self._sio.connected:
                self._connected = True
                if self._reconnect_task and not self._reconnect_task.done():
                    self._reconnect_task.cancel()
            
        except socketio.exceptions.ConnectionError:
            _LOGGER.warning("Socket connection attempt failed (ConnectionError). Scheduling reconnect.")
            self._schedule_reconnect()
        except Exception as exc:
            _LOGGER.error("Initial socket connection failed completely: %s", exc)
            self._connected = False
            self._schedule_reconnect()
            
    async def _push_state_to_listeners(self, data: Dict[str, Any]):
        for cb in list(self._listeners):
            self.hass.loop.call_soon_threadsafe(cb, data)
            
    async def _force_state_update_to_listeners(self, use_http_if_available: bool = False):
        if use_http_if_available:
            try:
                initial_state = await self.async_get_state()
                self._state = initial_state
            except Exception as exc:
                _LOGGER.warning("HTTP state fetch failed: %s. Relying on current cached state.", exc)
                
        await self._push_state_to_listeners(self._state)
            
    async def _notify_listeners_of_disconnect(self):
        self._state = {} 
        await self._push_state_to_listeners({}) 

    def add_listener(self, callback):
        if callback not in self._listeners:
            self._listeners.append(callback)
            self.hass.loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._push_state_to_listeners(self._state))
            )

    def remove_listener(self, callback):
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _schedule_reconnect(self):
        if self._connected:
            return

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        while not self._connected:
            delay = max(0.5, self._reconnect_delay)
            
            try:
                await self.async_connect() 
            except Exception:
                pass
            
            await asyncio.sleep(delay)
            self._reconnect_delay = min(self._reconnect_delay * 2, 300)
            
    async def async_disconnect(self):
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            
        if self._sio:
            try:
                if self._sio.connected:
                    await self._sio.disconnect()
            except Exception:
                pass
            self._sio = None
            
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

        self._connected = False