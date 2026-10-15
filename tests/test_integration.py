"""Setup, flow, discovery, migrations, and entity values."""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.apc_ups_snmp import async_migrate_entry
from custom_components.apc_ups_snmp.catalog import ATS, UPS, measurements, status
from custom_components.apc_ups_snmp.const import DOMAIN
from custom_components.apc_ups_snmp.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.apc_ups_snmp.snmp_client import (
    SnmpAuthError,
    SnmpConnectionError,
)

from .conftest import read_walk


@pytest.mark.parametrize("version", ["v1", "v2c", "v3"])
@pytest.mark.parametrize(
    "kind,fixture", [("ups", "smartups.walk"), ("ats", "ap4452a.walk")]
)
async def test_flow(hass, fake_snmp, version, kind, fixture):
    fake_snmp.fixture = fixture
    with patch("custom_components.apc_ups_snmp.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": "192.0.2.1",
                "port": 161,
                "snmp_version": version,
            },
        )
        assert result["step_id"] == ("auth_v3" if version == "v3" else "auth_v2c")
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "username": "monitor",
                "auth_protocol": "SHA",
                "auth_password": "secret",
                "priv_protocol": "AES",
                "priv_password": "private",
            }
            if version == "v3"
            else {"community": "readonly"},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"]["device_type"] == kind
        assert result["result"].version == 2


@pytest.mark.parametrize(
    "kind,fixture", [("ups", "smartups.walk"), ("ats", "ap4452a.walk")]
)
async def test_setup(hass, fake_snmp, kind, fixture):
    fake_snmp.fixture = fixture
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="APC",
        version=2,
        data={
            "host": "192.0.2.1",
            "port": 161,
            "snmp_version": "v1",
            "community": "readonly",
            "device_type": kind,
            "sensors": ["battery_capacity"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert len(entries) > 20

    def entity(key):
        return registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")

    if kind == "ups":
        assert hass.states.get(entity("battery_capacity")).state == "98.7"
        assert hass.states.get(entity("battery_runtime")).state == "30.0"
        assert hass.states.get(entity("output_voltage")).state == "120.1"
        assert hass.states.get(entity("ups_status")).state == "OL"
        assert hass.states.get(entity("outlet_group_1")).state == "on"
        assert entity("output_efficiency") is None
        assert registry.async_get(entity("battery_packs")).disabled_by is not None
    else:
        assert hass.states.get(entity("selected_source")).state == "Server UPS Blue"
        raw = read_walk(fixture)
        current = raw[ATS + ".5.4.3.1.4.1.1.1"] / 10
        assert float(hass.states.get(entity("output_current_1_1_1")).state) == current
        assert (
            hass.states.get(entity("output_power_1_1_1")).attributes[
                "unit_of_measurement"
            ]
            == "VA"
        )
        assert entity("bank_power_1") is None
    assert max(len(oids) for oids, _ in fake_snmp.calls) <= 20
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["config"]["community"] == "**REDACTED**"
    assert diagnostics["config"]["host"] == "**REDACTED**"
    assert "readonly" not in str(diagnostics)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_migration(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, data={"sensors": ["battery_capacity"]}
    )
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry)
    assert entry.version == 2
    assert entry.data["device_type"] == "ups"
    assert entry.data["sensors"] == ["battery_capacity"]


@pytest.mark.parametrize("source", ["reauth", "reconfigure"])
async def test_update_flow(hass, fake_snmp, source):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="AS0000000001",
        data={
            "host": "192.0.2.1",
            "port": 161,
            "snmp_version": "v2c",
            "community": "old",
            "device_type": "ups",
        },
    )
    entry.add_to_hass(hass)
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": source,
                "entry_id": entry.entry_id,
            },
            data=dict(entry.data) if source == "reauth" else None,
        )
        if source == "reauth":
            assert result["step_id"] == "reauth_confirm"
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {}
            )
        else:
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {
                    "host": "192.0.2.2",
                    "port": 161,
                    "snmp_version": "v1",
                },
            )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"community": "new"}
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == source + "_successful"
        assert entry.data["community"] == "new"
        assert entry.data["host"] == (
            "192.0.2.2" if source == "reconfigure" else "192.0.2.1"
        )


async def test_options(hass, fake_snmp):
    entry = MockConfigEntry(domain=DOMAIN, data={}, version=2)
    entry.add_to_hass(hass)
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload", return_value=True
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert len(result["data_schema"].schema) == 1
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 60}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    "error,expected",
    [(SnmpAuthError, "invalid_auth"), (SnmpConnectionError, "cannot_connect")],
)
async def test_flow_errors(hass, fake_snmp, error, expected):
    with patch.object(fake_snmp, "async_test_connection", side_effect=error):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": "192.0.2.1",
                "port": 161,
                "snmp_version": "v1",
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"community": "bad"}
        )
        assert result["errors"]["base"] == expected


def test_fallback_and_status():
    data = read_walk("smartups.walk")
    values = {item.key: item.value(data) for item in measurements("ups", data)}
    assert values["input_max_voltage"] == 125
    assert values["battery_current"] == 1.2
    assert values["battery_last_replaced"] == "06/01/2024"
    assert values["calibration_date"] == "09/01/2026"
    assert values["nominal_apparent_power"] == 1500
    data.update(
        {
            UPS + ".4.1.1.0": 3,
            UPS + ".2.1.1.0": 4,
            UPS + ".2.2.4.0": 2,
            UPS + ".7.2.6.0": 3,
            UPS + ".4.3.3.0": 1001,
        }
    )
    assert status(data) == "OB LB RB CAL OVER"


def test_energy_and_negative_efficiency():
    data = {UPS + ".4.3.6.0": 12345, UPS + ".4.3.5.0": -2}
    values = {item.key: item.value(data) for item in measurements("ups", data)}
    assert values["output_energy"] == 123.45
    assert values["output_efficiency"] is None
    assert (
        status({UPS + ".4.1.1.0": 2, UPS + ".4.2.3.0": None, UPS + ".4.3.3.0": None})
        == "OL"
    )


def test_ats_enum_meanings():
    data = read_walk("ap4452a.walk")
    data[ATS + ".4.2.0"] = 3
    values = {item.key: item.value(data) for item in measurements("ats", data)}
    assert values["preferred_source"] == "none"
    assert values["input_orientation_1"] == "single_phase"
    assert values["input_type_1"] == "main"
    assert values["input_status_1"] == "ok"


async def test_device_info_and_unavailability(hass, fake_snmp):
    from homeassistant.helpers import device_registry as dr

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        data={
            "host": "192.0.2.1",
            "port": 161,
            "snmp_version": "v2c",
            "device_type": "ups",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device.serial_number == "AS0000000001"
    assert device.sw_version == "UPS 15.0"
    assert device.configuration_url == "http://192.0.2.1"
    coordinator = hass.data[DOMAIN][entry.entry_id]
    data = dict(coordinator.data)
    data[UPS + ".4.3.1.0"] = None
    data[UPS + ".4.2.1.0"] = None
    coordinator.async_set_updated_data(data)
    await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_output_voltage"
    )
    assert hass.states.get(entity_id).state == "unavailable"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_coordinator_auth_failure(hass, fake_snmp):
    from homeassistant.exceptions import ConfigEntryAuthFailed

    from custom_components.apc_ups_snmp.coordinator import ApcUpsCoordinator

    coordinator = ApcUpsCoordinator(
        hass, {"host": "192.0.2.1", "port": 161, "snmp_version": "v1"}
    )
    with (
        patch.object(
            coordinator._client, "async_get_all_data", side_effect=SnmpAuthError
        ),
        pytest.raises(ConfigEntryAuthFailed),
    ):
        await coordinator._async_update_data()
    coordinator.close()


async def test_mismatched_reconfigure(hass, fake_snmp):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="OTHER",
        data={
            "host": "192.0.2.1",
            "port": 161,
            "snmp_version": "v2c",
            "community": "original",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "192.0.2.2",
            "port": 161,
            "snmp_version": "v2c",
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"community": "new"}
    )
    assert result["reason"] == "device_mismatch"
    assert entry.data["community"] == "original"


async def test_invalid_host(hass, fake_snmp):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "bad host!",
            "port": 161,
            "snmp_version": "v1",
        },
    )
    assert result["errors"]["host"] == "invalid_host"


def test_overload_bit_flag():
    flags = "000100001" + "0" * 55
    assert status({UPS + ".4.1.1.0": 2, UPS + ".11.1.1.0": flags}) == "OL OVER"


def test_phase_scaling_and_units():
    data = {
        UPS + ".9.3.3.1.7.1.1.1": 450,
        UPS + ".9.3.3.1.13.1.1.1": 400,
        UPS + ".9.2.2.1.4.1": 599,
    }
    items = {item.key: item for item in measurements("ups", data)}
    assert items["output_phase_power_1_1_1"].unit == "VA"
    assert items["output_phase_real_power_1_1_1"].unit == "W"
    assert items["input_frequency"].value(data) == 59.9
