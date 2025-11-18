"""Config flow for YTMDesktop v2 integration."""

from __future__ import annotations
import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import DOMAIN, DEFAULT_PORT, CONF_HOST, CONF_PORT, CONF_TOKEN, CONF_APP_ID, CONF_APP_NAME, CONF_APP_VERSION
from .api_client import YTMDClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST, default="localhost"): str,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    vol.Optional(CONF_APP_NAME, default="HA YTMDesktop Integration"): str,
    vol.Optional(CONF_APP_VERSION, default="0.1"): str,
})

class YTMDConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None):
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)

        host = user_input[CONF_HOST]
        port = user_input.get(CONF_PORT, DEFAULT_PORT)
        app_name = user_input.get(CONF_APP_NAME)
        app_version = user_input.get(CONF_APP_VERSION)

        # create temporary client to request code
        client = YTMDClient(self.hass, host, port, token=None)
        try:
            request_code = await client.async_request_code(app_name=app_name, app_version=app_version)
        except Exception as exc:
            _LOGGER.exception("Failed to request code: %s", exc)
            return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors={"base": "connection"})

        # request_code should contain {"code": "...", "expires": "...", ...}
        code = request_code.get("code") if isinstance(request_code, dict) else None
        if not code:
            _LOGGER.error("No code in response")
            return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors={"base": "connection"})

        # store temp data and instruct user to authorize in YTMDesktop
        self._temp_data = {
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_APP_NAME: app_name,
            CONF_APP_VERSION: app_version,
            "request_code": request_code,
        }

        return self.async_show_form(
            step_id="authorize",
            description_placeholders={"code": code, "host": f"{host}:{port}"},
            data_schema=vol.Schema({vol.Required("confirm", default=True): bool}),
        )

    async def async_step_authorize(self, user_input: Optional[Dict[str, Any]] = None):
        """Exchange code for token after user confirms they've authorized on YTMDesktop."""
        if user_input is None:
            # Should not happen — this step is only shown after user confirms
            return self.async_abort(reason="unknown")

        host = self._temp_data[CONF_HOST]
        port = self._temp_data[CONF_PORT]
        app_name = self._temp_data[CONF_APP_NAME]
        app_version = self._temp_data[CONF_APP_VERSION]
        request_code = self._temp_data["request_code"]
        code = request_code.get("code")

        client = YTMDClient(self.hass, host, port, token=None)
        try:
            token_response = await client.async_request_token(code, app_name=app_name, app_version=app_version)
        except Exception as exc:
            _LOGGER.exception("Token request failed: %s", exc)
            return self.async_show_form(step_id="authorize", errors={"base": "token"})

        token = token_response.get("token") if isinstance(token_response, dict) else token_response
        if not token:
            _LOGGER.error("No token returned")
            return self.async_show_form(step_id="authorize", errors={"base": "token"})

        # Create config entry
        data = {
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_TOKEN: token,
            CONF_APP_NAME: app_name,
            CONF_APP_VERSION: app_version,
            CONF_APP_ID: token_response.get("appId", "ha-ytmd-v2")
        }

        return self.async_create_entry(title=f"YTMDesktop @ {host}", data=data)
