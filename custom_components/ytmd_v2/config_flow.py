import logging
from typing import Any, Dict, Optional
import asyncio

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult, AbortFlow
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

class YTMDConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH
    
    # State management between steps
    _user_input: Optional[Dict[str, Any]] = None
    _numeric_code: Optional[str] = None
    _polling_task: Optional[asyncio.Task] = None

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle the initial step to gather connection info and request code."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)

        self._user_input = user_input
        host = user_input[CONF_HOST]
        port = user_input.get(CONF_PORT, DEFAULT_PORT)
        app_name = user_input.get(CONF_APP_NAME)
        app_version = user_input.get(CONF_APP_VERSION)
        app_id = "ha-ytmd-v2"

        client = YTMDClient(self.hass, host, port, token=None)
        
        try:
            # STEP 1: Request code.
            request_code = await client.async_request_code(
                app_name=app_name, app_version=app_version, app_id=app_id
            )
            code = request_code.get("code")
            
            if not code:
                _LOGGER.error("No numeric code returned from YTMD server")
                raise ValueError("No numeric code returned")

            self._numeric_code = code

            # Transition to the authorization check step
            return await self.async_step_auth_check()

        except (YTMDConnectionError, YTMDAuthError, ValueError) as exc:
            _LOGGER.exception("Config flow failed at user step: %s", exc)
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


    async def async_step_auth_check(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle the authorization check and polling step."""
        
        host = self._user_input[CONF_HOST]
        port = self._user_input.get(CONF_PORT, DEFAULT_PORT)
        code = self._numeric_code
        
        if self._polling_task is None:
            # Polling is what triggers the YTMDesktop app's approval prompt
            self._polling_task = self.hass.async_create_task(self._async_poll_for_token())
            _LOGGER.info("Starting background token polling to initiate YTMDesktop approval.")

        # --- Display the form with the code (Always visible) ---
        description_placeholders = {"code": code}
        
        if user_input is None or not user_input.get("approved"):
            errors = {}
            if user_input is not None:
                # User submitted without checking the box
                errors = {"base": "not_approved"}

            return self.async_show_form(
                step_id="auth_check", 
                data_schema=vol.Schema({vol.Required("approved", default=False): bool}),
                description_placeholders=description_placeholders,
                errors=errors,
            )
        
        # --- User checked "approved" and hit submit ---
        
        # Check the result of the background polling task
        if self._polling_task.done():
            try:
                # If the task is done, it either succeeded (result is token) or failed (exception)
                token = self._polling_task.result()
                if token:
                    # Successful poll result was stored on the flow by _async_poll_for_token
                    return self.async_create_entry(title=f"YTMDesktop @ {host}", data=self._user_input)
                else:
                    # Task returned None or something unexpected
                    raise AbortFlow("auth_timeout")
            except AbortFlow as exc:
                # AbortFlow raised by the polling task itself (e.g., timeout)
                return self.async_abort(reason=exc.reason)
            except Exception as exc:
                _LOGGER.exception("Token polling failed unexpectedly.")
                return self.async_abort(reason="unknown")
        
        # If the task is still running, refresh the form with a temporary message
        return self.async_show_form(
            step_id="auth_check", 
            data_schema=vol.Schema({vol.Required("approved", default=False): bool}),
            description_placeholders=description_placeholders,
            errors={"base": "still_polling"},
        )


    async def _async_poll_for_token(self):
        """Background task to poll the API for the permanent token."""
        host = self._user_input[CONF_HOST]
        port = self._user_input.get(CONF_PORT, DEFAULT_PORT)
        app_id = "ha-ytmd-v2"
        code = self._numeric_code
        
        client = YTMDClient(self.hass, host, port, token=None)
        
        token = None
        elapsed = 0
        try:
            while elapsed < APPROVAL_TIMEOUT:
                try:
                    token_response = await client.async_request_token(code=code, app_id=app_id)
                    token = token_response.get("token")
                    if token:
                        _LOGGER.info("Token successfully retrieved. Polling complete.")
                        # Store the token and exit the task successfully
                        self._user_input[CONF_TOKEN] = token
                        self._user_input[CONF_APP_ID] = app_id
                        
                        # Tell the flow to finish successfully
                        self.hass.async_create_task(
                            self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
                        )
                        return token # Return token to the task result
                    
                except YTMDConnectionError:
                    _LOGGER.debug("Token request failed (waiting for approval)")
                except Exception as exc:
                    _LOGGER.debug("Token request failed with unexpected error: %s", exc)
                    
                await asyncio.sleep(RETRY_INTERVAL)
                elapsed += RETRY_INTERVAL

            _LOGGER.error("Token was not approved in time (Polling timeout).")
            raise AbortFlow("auth_timeout")

        except Exception as exc:
            # If the task fails, notify the flow handler
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
            )
            raise # Re-raise exception to be caught by the calling task
        finally:
            await client.async_disconnect()


    async def async_step_auth_check_reconfirm(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        # Re-using the primary step for simplicity.
        return await self.async_step_auth_check(user_input)
        
    async def async_step_reauth(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle reauthorization. Not fully implemented here, but good practice."""
        return self.async_abort(reason="reauth_unsupported")

    async def async_step_abort(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Cleanup logic when the flow aborts or finishes."""
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
            _LOGGER.info("Cancelled background token polling task.")
        return await super().async_step_abort(user_input)