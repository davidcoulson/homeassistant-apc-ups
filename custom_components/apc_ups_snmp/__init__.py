"""APC UPS SNMP Integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_SNMP_VERSION, DEFAULT_SCAN_INTERVAL, DOMAIN, SNMP_VERSION_2C
from .coordinator import ApcUpsCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up APC UPS SNMP from a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Config entry.

    Returns:
        True if setup was successful.
    """
    _LOGGER.debug("Setting up APC UPS SNMP integration: %s", entry.title)

    # Warn about SNMP v2c security implications
    if entry.data.get(CONF_SNMP_VERSION) in ("v1", SNMP_VERSION_2C):
        _LOGGER.warning(
            "APC UPS '%s' is using SNMP v1/v2c which transmits credentials in plaintext. "
            "Consider reconfiguring with SNMP v3 for better security",
            entry.title,
        )

    # Get scan interval from options, falling back to default
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

    # Create coordinator
    coordinator = ApcUpsCoordinator(
        hass=hass,
        config_data=entry.data,
        update_interval=int(scan_interval),
    )

    # Fetch initial data
    try:
        await coordinator.async_config_entry_first_refresh()
    except BaseException:
        coordinator.close()
        raise

    # Store coordinator
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Config entry.

    Returns:
        True if unload was successful.
    """
    _LOGGER.debug("Unloading APC UPS SNMP integration: %s", entry.title)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: ApcUpsCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.close()

        # Remove shared integration storage after the last entry.
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update.

    Args:
        hass: Home Assistant instance.
        entry: Config entry.
    """
    _LOGGER.debug("Updating options for APC UPS SNMP: %s", entry.title)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass, entry):
    """Preserve entity IDs and default legacy entries to UPS."""
    if entry.version > 2:
        return False
    if entry.version == 1:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, "device_type": entry.data.get("device_type", "ups")},
            version=2,
        )
    return True
