"""DataUpdateCoordinator for APC UPS SNMP integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_AUTH_PASSWORD,
    CONF_AUTH_PROTOCOL,
    CONF_COMMUNITY,
    CONF_PRIV_PASSWORD,
    CONF_PRIV_PROTOCOL,
    CONF_SNMP_VERSION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SNMP_VERSION_2C,
    SNMP_VERSION_3,
)
from .snmp_client import (
    ApcSnmpClient,
    SnmpAuthError,
    SnmpConnectionError,
    SnmpTimeoutError,
)

_LOGGER = logging.getLogger(__name__)


class ApcUpsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for APC UPS SNMP data."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_data: dict[str, Any],
        update_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance.
            config_data: Configuration data from config entry.
            update_interval: Update interval in seconds.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

        self._config_data = config_data
        self._client = self._create_client()
        self._client.device_type = config_data.get("device_type", "ups")

    def _create_client(self) -> ApcSnmpClient:
        """Create an SNMP client from config data."""
        if self._config_data.get(CONF_SNMP_VERSION) in ("v1", SNMP_VERSION_2C):
            return ApcSnmpClient(
                host=self._config_data[CONF_HOST],
                port=self._config_data[CONF_PORT],
                version=self._config_data.get(CONF_SNMP_VERSION, SNMP_VERSION_2C),
                community=self._config_data.get(CONF_COMMUNITY),
            )
        else:
            return ApcSnmpClient(
                host=self._config_data[CONF_HOST],
                port=self._config_data[CONF_PORT],
                version=SNMP_VERSION_3,
                username=self._config_data.get(CONF_USERNAME),
                auth_protocol=self._config_data.get(CONF_AUTH_PROTOCOL),
                auth_password=self._config_data.get(CONF_AUTH_PASSWORD),
                priv_protocol=self._config_data.get(CONF_PRIV_PROTOCOL),
                priv_password=self._config_data.get(CONF_PRIV_PASSWORD),
            )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the UPS.

        Returns:
            Dictionary mapping OIDs to their values.

        Raises:
            UpdateFailed: If data fetch fails.
            ConfigEntryAuthFailed: If authentication fails.
        """
        try:
            data = await self._client.async_get_all_data()
            _LOGGER.debug("Fetched %d OID values from UPS", len(data))
            return data

        except SnmpAuthError as err:
            raise ConfigEntryAuthFailed(
                f"Authentication failed - check credentials: {err}"
            ) from err

        except SnmpTimeoutError as err:
            raise UpdateFailed(f"Timeout connecting to UPS: {err}") from err

        except SnmpConnectionError as err:
            raise UpdateFailed(f"Error connecting to UPS: {err}") from err

        except Exception as err:
            _LOGGER.exception("Unexpected error fetching UPS data")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def close(self) -> None:
        """Close the SNMP client."""
        self._client.close()
