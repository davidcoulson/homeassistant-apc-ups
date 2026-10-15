"""DataUpdateCoordinator for APC UPS SNMP integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
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

        self.config_data = config_data
        self._client = ApcSnmpClient.from_config(self.config_data)
        self._client.device_type = config_data.get("device_type", "ups")

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
