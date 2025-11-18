"""Config flow for YTMDesktop v2 integration with HA notifications for token approval."""

import logging
from typing import Any, Dict, Optional
import asyncio

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.persistent_notification import async_create, async_remove

from .const import DOMAIN, DEFAULT_PORT, CONF_HOST, CONF_PORT, CONF_APP_NAME, CONF_APP_VERSION, CONF_TOKEN, CONF_APP_ID
from .api_client import YTMDClient, YTMDConnectionError, YTMDAuthError # Import custom exceptions

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST, default="localhost"): str,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
    vol.Optional(CONF_APP_NAME, default="HA YTMDesktop Integration"): str,
    vol.Optional(CONF_APP_VERSION, default="0.1.0"): str,
})

APPROVAL_TIMEOUT = 60  # seconds
RETRY_INTERVAL = 3     # seconds
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
            # Step 1: request numeric code
            request_code = await client.async_request_code(
                app_name=app_name, app_version=app_version, app_id=app_id
            )
            code = request_code.get("code")
            if not code:
                _LOGGER.error("No numeric code returned from YTMD server")
                raise ValueError("No numeric code returned")

            _LOGGER.info("Numeric code received: %s", code)
            await self._show_approval_notification(code)

            # Step 2: wait until user approves code to get permanent token
            token = None
            elapsed = 0
            while elapsed < APPROVAL_TIMEOUT:
                try:
                    token_response = await client.async_request_token(code=code, app_id=app_id)
                    token = token_response.get("token")
                    if token:
                        break
                except YTMDConnectionError:
                    # Expected if token is not yet approved
                    _LOGGER.debug("Token request failed (waiting for approval)")
                except Exception as exc:
                    _LOGGER.debug("Token request failed with unexpected error: %s", exc)
                
                await asyncio.sleep(RETRY_INTERVAL)
                elapsed += RETRY_INTERVAL

            if not token:
                _LOGGER.error("Token was not approved in time")
                raise ValueError("Token not approved")

            # Remove the notification once token is retrieved
            async_remove(self.hass, NOTIFICATION_ID)
            
            # Create data payload
            data = {
                CONF_HOST: host,
                CONF_PORT: port,
                CONF_TOKEN: token,
                CONF_APP_NAME: app_name,
                CONF_APP_VERSION: app_version,
                CONF_APP_ID: app_id,
            }

            # Return success entry
            return self.async_create_entry(title=f"YTMDesktop @ {host}", data=data)


        except (YTMDConnectionError, YTMDAuthError, ValueError) as exc:
            # Catch all expected connection/auth/logic errors
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
            # IMPORTANT: Ensure the temporary client's session is closed
            await client.async_disconnect()


    async def _show_approval_notification(self, code: str):
        """Show a persistent notification in HA prompting the user to approve the numeric code."""
        message = (
            f"Please open YTMDesktop on your computer and approve the following numeric code:\n\n"
            f"**{code}**\n\n"
            "This is required to complete the Home Assistant integration."
        )
        async_create(
            self.hass,
            message=message,
            title="YTMDesktop Authorization Required",
            notification_id=NOTIFICATION_ID,
        )