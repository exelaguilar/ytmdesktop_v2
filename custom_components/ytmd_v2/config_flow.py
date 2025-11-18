import logging
from typing import Any, Dict, Optional
import asyncio

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import (
    DOMAIN, 
    DEFAULT_PORT, 
    CONF_HOST, 
    CONF_PORT, 
    CONF_APP_NAME, 
    CONF_APP_VERSION, 
    CONF_TOKEN, 
    CONF_APP_ID
)
from .api_client import YTMDClient, YTMDConnectionError, YTMDAuthError 

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST, default="localhost"): str,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    vol.Optional(CONF_APP_NAME, default="HA YTMDesktop Integration"): str,
    vol.Optional(CONF_APP_VERSION, default="0.1.0"): str,
})

APPROVAL_TIMEOUT = 60
RETRY_INTERVAL = 3
NOTIFICATION_ID = "ytmd_authorization"


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
        app_id = "ha-ytmd-v2"

        client = YTMDClient(self.hass, host, port, token=None)
        
        try:
            request_code = await client.async_request_code(
                app_name=app_name, app_version=app_version, app_id=app_id
            )
            code = request_code.get("code")
            if not code:
                _LOGGER.error("No numeric code returned from YTMD server")
                raise ValueError("No numeric code returned")

            _LOGGER.info("Numeric code received: %s", code)
            
            await self._show_approval_notification(code)

            token = None
            elapsed = 0
            while elapsed < APPROVAL_TIMEOUT:
                try:
                    token_response = await client.async_request_token(code=code, app_id=app_id)
                    token = token_response.get("token")
                    if token:
                        break
                except YTMDConnectionError:
                    _LOGGER.debug("Token request failed (waiting for approval)")
                except Exception as exc:
                    _LOGGER.debug("Token request failed with unexpected error: %s", exc)
                    
                await asyncio.sleep(RETRY_INTERVAL)
                elapsed += RETRY_INTERVAL

            if not token:
                _LOGGER.error("Token was not approved in time")
                raise ValueError("Token not approved")

            await self.hass.services.async_call(
                "persistent_notification", 
                "dismiss", 
                {"notification_id": NOTIFICATION_ID},
                blocking=True,
            )
            
            data = {
                CONF_HOST: host,
                CONF_PORT: port,
                CONF_TOKEN: token,
                CONF_APP_NAME: app_name,
                CONF_APP_VERSION: app_version,
                CONF_APP_ID: app_id,
            }

            return self.async_create_entry(title=f"YTMDesktop @ {host}", data=data)


        except (YTMDConnectionError, YTMDAuthError, ValueError) as exc:
            _LOGGER.exception("Config flow failed: %s", exc)
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors={"base": "connection"}
            )
        except Exception as exc:
            _LOGGER.exception("An unexpected error occurred during config flow.")
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors={"base": "unknown"}
            )
        finally:
            await client.async_disconnect()


    async def _show_approval_notification(self, code: str):
        message = (
            f"Please open YTMDesktop on your computer and approve the following numeric code:\n\n"
            f"**{code}**\n\n"
            "This is required to complete the Home Assistant integration."
        )
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "message": message,
                "title": "YTMDesktop Authorization Required",
                "notification_id": NOTIFICATION_ID,
            },
            blocking=True,
        )