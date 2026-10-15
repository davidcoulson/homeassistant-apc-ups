"""Redacted raw SNMP diagnostics."""

from homeassistant.components.diagnostics import async_redact_data

from .const import DOMAIN

REDACT = {"host", "community", "username", "auth_password", "priv_password", "serial"}


async def async_get_config_entry_diagnostics(hass, entry):
    """Include raw values without exposing credentials or identifying fields."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    from .catalog import IDENTITY

    raw = dict(coordinator.data or {})
    for identity in IDENTITY.values():
        for field in ("serial", "name"):
            if identity[field] in raw:
                raw[identity[field]] = "**REDACTED**"
    return {
        "config": async_redact_data(dict(entry.data), REDACT),
        "options": dict(entry.options),
        "data": raw,
    }
