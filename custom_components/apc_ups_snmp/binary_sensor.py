"""Binary sensor platform for APC UPS SNMP integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .catalog import ATS, ATS_PROBLEMS, status
from .const import (
    BATTERY_REPLACE_YES,
    BATTERY_STATUS_LOW,
    DOMAIN,
    OUTPUT_STATUS_ON_BATTERY,
    ApcOid,
)
from .coordinator import ApcUpsCoordinator
from .entity import ApcUpsEntity


@dataclass(frozen=True)
class ApcUpsBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Describes an APC UPS binary sensor entity."""

    oid: str | None = None
    is_on_fn: Callable[[dict[str, Any]], bool | None] | None = None


def is_on_battery(data: dict[str, Any]) -> bool | None:
    """Check if UPS is running on battery."""
    status = data.get(ApcOid.OUTPUT_STATUS)
    if status is None:
        return None
    return status == OUTPUT_STATUS_ON_BATTERY


def needs_battery_replacement(data: dict[str, Any]) -> bool | None:
    """Check if battery needs replacement."""
    replace = data.get(ApcOid.BATTERY_REPLACE)
    if replace is None:
        return None
    return replace == BATTERY_REPLACE_YES


def is_low_battery(data: dict[str, Any]) -> bool | None:
    """Check if battery is low."""
    status = data.get(ApcOid.BATTERY_STATUS)
    if status is None:
        return None
    return status in (BATTERY_STATUS_LOW, 4, 5)


BINARY_SENSOR_DESCRIPTIONS: list[ApcUpsBinarySensorEntityDescription] = [
    ApcUpsBinarySensorEntityDescription(
        key="on_battery",
        translation_key="on_battery",
        name="On Battery",
        device_class=BinarySensorDeviceClass.POWER,
        is_on_fn=is_on_battery,
    ),
    ApcUpsBinarySensorEntityDescription(
        key="replace_battery",
        translation_key="replace_battery",
        name="Replace Battery",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=needs_battery_replacement,
    ),
    ApcUpsBinarySensorEntityDescription(
        key="low_battery",
        translation_key="low_battery",
        name="Low Battery",
        device_class=BinarySensorDeviceClass.BATTERY,
        is_on_fn=is_low_battery,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up APC UPS SNMP binary sensors."""
    coordinator: ApcUpsCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = (
        BINARY_SENSOR_DESCRIPTIONS
        if entry.data.get("device_type", "ups") == "ups"
        else [
            ApcUpsBinarySensorEntityDescription(
                key=key,
                translation_key=key,
                entity_category=EntityCategory.DIAGNOSTIC
                if key not in ("redundancy_lost", "overcurrent")
                else None,
                entity_registry_enabled_default=key
                in ("redundancy_lost", "overcurrent"),
                name=key.replace("_", " ").capitalize(),
                device_class=BinarySensorDeviceClass.PROBLEM,
                is_on_fn=lambda data, oid=ATS + f".5.1.{column}.0": (
                    None if data.get(oid) is None else (data[oid] != 2)
                ),
            )
            for key, column in ATS_PROBLEMS.items()
        ]
    )
    entities = [
        ApcUpsBinarySensor(
            coordinator=coordinator,
            entry_id=entry.entry_id,
            description=description,
        )
        for description in descriptions
        if description.is_on_fn(coordinator.data) is not None
    ]

    async_add_entities(entities)


class ApcUpsBinarySensor(ApcUpsEntity, BinarySensorEntity):
    """Representation of an APC UPS binary sensor."""

    entity_description: ApcUpsBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: ApcUpsCoordinator,
        entry_id: str,
        description: ApcUpsBinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor.

        Args:
            coordinator: The data coordinator.
            entry_id: The config entry ID.
            description: The entity description.
        """
        super().__init__(coordinator, entry_id)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        if description.key in ("source_a_fault", "source_b_fault"):
            index = 1 if description.key == "source_a_fault" else 2
            self._attr_translation_placeholders = {
                "input": str(
                    coordinator.data.get(ATS + f".5.3.2.1.6.{index}")
                    or f"Source {'AB'[index - 1]}"
                )
            }

    @property
    def available(self):
        return super().available and self.is_on is not None

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.data is None:
            return None

        if self.entity_description.is_on_fn is not None:
            return self.entity_description.is_on_fn(self.coordinator.data)

        return None


# Derived flags share the same status semantics as the textual status sensor.
for _key, _word in (
    ("overload", "OVER"),
    ("on_bypass", "BYPASS"),
    ("calibrating", "CAL"),
):
    BINARY_SENSOR_DESCRIPTIONS.append(
        ApcUpsBinarySensorEntityDescription(
            key=_key,
            translation_key=_key,
            name=_key.replace("_", " ").capitalize(),
            device_class=BinarySensorDeviceClass.PROBLEM,
            is_on_fn=lambda data, word=_word: (
                None
                if status(data) is None
                else (
                    data.get(ApcOid.OUTPUT_STATUS) in (6, 9, 10, 16, 17)
                    if word == "BYPASS"
                    else word in status(data).split()
                )
            ),
        )
    )
