"""Config flow for APC UPS SNMP integration."""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    AUTH_PROTOCOLS,
    CONF_AUTH_PASSWORD,
    CONF_AUTH_PROTOCOL,
    CONF_COMMUNITY,
    CONF_PRIV_PASSWORD,
    CONF_PRIV_PROTOCOL,
    CONF_SNMP_VERSION,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    PRIV_PROTOCOLS,
    SNMP_VERSION_2C,
    SNMP_VERSION_3,
)
from .snmp_client import (
    ApcSnmpClient,
    SnmpAuthError,
    SnmpConfigError,
    SnmpConnectionError,
    SnmpTimeoutError,
    validate_v3,
)

_LOGGER = logging.getLogger(__name__)

# Regex for validating hostnames (RFC 1123)
_HOSTNAME_REGEX = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


def _validate_host(host: str) -> bool:
    """Validate host is a valid IP address or hostname.

    Args:
        host: The host string to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not host or len(host) > 253:
        return False

    # Try parsing as IP address first
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass

    # Check if valid hostname
    return bool(_HOSTNAME_REGEX.match(host))


class ApcUpsSnmpConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for APC UPS SNMP."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}
        self._ups_identity: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input = {**self._data, **user_input}
            self._data.update(user_input)
            # Validate host input
            host = user_input.get(CONF_HOST, "").strip()
            if not _validate_host(host):
                errors[CONF_HOST] = "invalid_host"
            else:
                user_input[CONF_HOST] = host  # Use trimmed value
                self._data.update(user_input)

                if user_input[CONF_SNMP_VERSION] in ("v1", SNMP_VERSION_2C):
                    return await self.async_step_auth_v2c()
                else:
                    return await self.async_step_auth_v3()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=self._data.get(CONF_HOST, vol.UNDEFINED)
                    ): str,
                    vol.Required(
                        CONF_PORT, default=self._data.get(CONF_PORT, DEFAULT_PORT)
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                    vol.Required(
                        CONF_SNMP_VERSION,
                        default=self._data.get(CONF_SNMP_VERSION, SNMP_VERSION_2C),
                    ): vol.In(["v1", SNMP_VERSION_2C, SNMP_VERSION_3]),
                }
            ),
            errors=errors,
        )

    async def async_step_auth_v2c(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle SNMP v2c authentication step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._update_credentials(user_input)

            # Test connection
            error = await self._test_connection()
            if isinstance(error, dict):
                errors.update(error)
            elif error:
                errors["base"] = error
            else:
                # Check for duplicate
                await self.async_set_unique_id(self._ups_identity.get("serial"))
                if self.source not in ("reauth", "reconfigure"):
                    self._abort_if_unique_id_configured()

                return await self.async_step_sensors()

        return self.async_show_form(
            step_id="auth_v2c",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_COMMUNITY, default=self._data.get(CONF_COMMUNITY, "public")
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_auth_v3(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle SNMP v3 authentication step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._update_credentials(user_input)

            errors = validate_v3(self._data)
            if not errors:
                error = await self._test_connection()
                if isinstance(error, dict):
                    errors.update(error)
                elif error:
                    errors["base"] = error
                else:
                    await self.async_set_unique_id(self._ups_identity.get("serial"))
                    if self.source not in ("reauth", "reconfigure"):
                        self._abort_if_unique_id_configured()
                    return await self.async_step_sensors()

        # Build options for selectors
        auth_options = [
            SelectOptionDict(value=proto, label=proto) for proto in AUTH_PROTOCOLS
        ]
        priv_options = [
            SelectOptionDict(value=proto, label=proto) for proto in PRIV_PROTOCOLS
        ]

        return self.async_show_form(
            step_id="auth_v3",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME,
                        description={"suggested_value": self._data.get(CONF_USERNAME)},
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Optional(
                        CONF_AUTH_PROTOCOL,
                        description={
                            "suggested_value": self._data.get(CONF_AUTH_PROTOCOL)
                        },
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=auth_options,
                            mode="dropdown",
                        )
                    ),
                    vol.Optional(CONF_AUTH_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(
                        CONF_PRIV_PROTOCOL,
                        description={
                            "suggested_value": self._data.get(CONF_PRIV_PROTOCOL)
                        },
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=priv_options,
                            mode="dropdown",
                        )
                    ),
                    vol.Optional(CONF_PRIV_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    def _update_credentials(self, user_input):
        """Keep blank stored passwords while retaining non-secret form input."""
        if self._data.get(CONF_SNMP_VERSION) in ("v1", SNMP_VERSION_2C):
            for key in (
                CONF_USERNAME,
                CONF_AUTH_PROTOCOL,
                CONF_AUTH_PASSWORD,
                CONF_PRIV_PROTOCOL,
                CONF_PRIV_PASSWORD,
            ):
                self._data.pop(key, None)
        else:
            self._data.pop(CONF_COMMUNITY, None)
        for key, value in user_input.items():
            if key in (CONF_AUTH_PASSWORD, CONF_PRIV_PASSWORD) and not value:
                continue
            self._data[key] = value

    async def async_step_sensors(self, user_input=None):
        """Finish setup after detection, without a sensor picker."""
        if self.source in ("reauth", "reconfigure"):
            entry = (
                self._get_reauth_entry()
                if self.source == "reauth"
                else self._get_reconfigure_entry()
            )
            if (
                entry.unique_id
                and self._ups_identity.get("serial") != entry.unique_id
                and self._ups_identity.get("manufacture_date") != entry.unique_id
            ):
                return self.async_abort(reason="device_mismatch")
            return self.async_update_reload_and_abort(
                entry,
                data=self._data,
                reason="reauth_successful"
                if self.source == "reauth"
                else "reconfigure_successful",
            )
        return self.async_create_entry(
            title=self._ups_identity.get("model") or "APC",
            data=self._data,
        )

    async def async_step_reauth(self, entry_data):
        """Change credentials after an authentication failure."""
        self._data = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        if user_input is not None:
            if self._data.get(CONF_SNMP_VERSION) in ("v1", SNMP_VERSION_2C):
                return await self.async_step_auth_v2c()
            return await self.async_step_auth_v3()
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=vol.Schema({})
        )

    async def async_step_reconfigure(self, user_input=None):
        """Use the normal connection forms to change host or credentials."""
        if not self._data:
            self._data = dict(self._get_reconfigure_entry().data)
        return await self.async_step_user(user_input)

    async def _test_connection(self) -> str | dict[str, str] | None:
        """Test the SNMP connection and get UPS identity.

        Returns:
            Error string if connection failed, None if successful.
        """
        client = None
        try:
            client = ApcSnmpClient.from_config(self._data)
            if not await client.async_test_connection():
                return "cannot_connect"
            self._data["device_type"] = client.device_type
            self._ups_identity = await client.async_get_identity()
            return None
        except SnmpConfigError as err:
            return err.errors
        except (ValueError, TypeError):
            return "invalid_security"
        except SnmpTimeoutError:
            return "timeout"
        except SnmpAuthError:
            return "invalid_auth"
        except SnmpConnectionError:
            return "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error during connection test")
            return "unknown"
        finally:
            if client is not None:
                client.close()

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return ApcUpsSnmpOptionsFlow(config_entry)


class ApcUpsSnmpOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for APC UPS SNMP."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        # Store config_entry for backward compatibility with older HA versions
        # In newer HA (2023.4+), self.config_entry is set automatically by framework
        super().__init__()
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Use framework-provided config_entry if available, else use stored one
        entry = getattr(self, "config_entry", None) or self._entry

        current_scan_interval = entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=current_scan_interval
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=5,
                            unit_of_measurement="seconds",
                            mode=NumberSelectorMode.SLIDER,
                        )
                    ),
                }
            ),
        )
