"""Automatically discovered UPS and ATS measurements."""

import re

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.helpers.entity import EntityCategory

from .catalog import measurements, status
from .const import DOMAIN
from .entity import ApcUpsEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Create all supported measurements, including indexed rows."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    kind = entry.data.get("device_type", "ups")
    entities = [
        ApcUpsSensor(coordinator, entry.entry_id, item)
        for item in measurements(kind, coordinator.data)
        if item.value(coordinator.data) is not None
    ]
    if kind == "ups" and status(coordinator.data) is not None:
        entities.append(ApcUpsSensor(coordinator, entry.entry_id, None))
    async_add_entities(entities)


class ApcUpsSensor(ApcUpsEntity, SensorEntity):
    """A measurement with per-OID scaling and precision fallback."""

    def __init__(self, coordinator, entry_id, measurement):
        super().__init__(coordinator, entry_id)
        self.measurement = measurement
        key = measurement.key if measurement else "ups_status"
        self._attr_unique_id = f"{entry_id}_{key}"
        enum = measurement.enum if measurement else None
        translation_key = re.sub(r"_\d+(?:_\d+)*$", "_indexed", key)
        if translation_key != key:
            label = measurement.name or key.replace("_", " ").capitalize()
            base = translation_key.removesuffix("_indexed")
            if base != "outlet_group":
                metric = (
                    base.removeprefix("input_")
                    .removeprefix("output_")
                    .removeprefix("bank_")
                    .removeprefix("phase_")
                    .replace("_", " ")
                )
                row = re.search(r" (phase|bank) (\d+)$", label)
                if row:
                    label = label[: row.start()]
                    translation_key += "_" + row[1]
                label = label.removesuffix(" " + metric)
                self._attr_translation_placeholders = {"label": label}
                if row:
                    self._attr_translation_placeholders["index"] = row[2]
            else:
                self._attr_translation_placeholders = {"label": label}
        if key in ("selected_source", "preferred_source"):
            translation_key = None
        self.entity_description = SensorEntityDescription(
            key=key,
            translation_key=translation_key,
            name=(measurement.name if measurement else None)
            or key.replace("_", " ").capitalize(),
            native_unit_of_measurement=measurement.unit if measurement else None,
            device_class=SensorDeviceClass.ENUM
            if enum
            else (measurement.device_class if measurement else None),
            options=list(dict.fromkeys(enum.values())) if enum else None,
            state_class=(
                SensorStateClass.TOTAL_INCREASING
                if key == "output_energy"
                else SensorStateClass.MEASUREMENT
            )
            if measurement and measurement.unit
            else None,
            entity_category=EntityCategory.DIAGNOSTIC
            if measurement and measurement.diagnostic
            else None,
            entity_registry_enabled_default=not (
                measurement and measurement.diagnostic
            ),
        )

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return self.measurement.value(data) if self.measurement else status(data)

    @property
    def available(self):
        return super().available and self.native_value is not None
