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
                "auth_password": "secret123",
                "priv_protocol": "AES",
                "priv_password": "private123",
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
        assert entity("input_status_1") is None
        assert (
            registry.async_get(entity("output_current_1_1_1")).original_name
            == "Output current"
        )
        assert (
            registry.async_get(entity("input_voltage_1_1_1")).original_name
            == "Server UPS Blue voltage"
        )
        source_id = registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{entry.entry_id}_source_a_fault"
        )
        assert registry.async_get(source_id).original_name == "Server UPS Blue fault"
        assert registry.async_get(source_id).disabled_by is not None
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
    assert "input_status_1" not in values


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


def test_row_names_diagnostics_and_duplicates():
    from unittest.mock import MagicMock

    from custom_components.apc_ups_snmp.sensor import ApcUpsSensor

    data = read_walk("ap4452a.walk")
    items = {item.key: item for item in measurements("ats", data)}
    assert items["input_voltage_1_1_1"].name == "Server UPS Blue voltage"
    assert items["input_frequency_2"].name == "Server UPS Green frequency"
    assert items["output_current_1_1_1"].name == "Output current"
    for key in ("input_orientation_1", "input_type_1", "output_frequency_1"):
        assert items[key].diagnostic
    assert not any(key.startswith("input_status_") for key in items)
    assert not any(item.key == "ups_temperature" for item in measurements("ups", {}))
    assert not any(key.startswith("bank_") for key in items)
    data[ATS + ".5.4.3.1.4.1.1.2"] = 25
    multi = {item.key: item for item in measurements("ats", data)}
    assert multi["output_current_1_1_1"].name == "Output current phase 1"
    assert multi["output_current_1_1_2"].name == "Output current phase 2"
    entity = ApcUpsSensor(MagicMock(), "entry", multi["output_current_1_1_2"])
    assert entity.unique_id == "entry_output_current_1_1_2"
    assert entity.translation_key == "output_current_indexed_phase"
    assert entity.translation_placeholders == {"label": "Output", "index": "2"}


def test_all_enum_translations():
    import json
    import re
    from pathlib import Path
    from unittest.mock import MagicMock

    from custom_components.apc_ups_snmp.sensor import ApcUpsSensor

    strings = json.loads(
        Path("custom_components/apc_ups_snmp/strings.json").read_text()
    )
    translations = strings["entity"]["sensor"]
    data = read_walk("ap4452a.walk") | read_walk("smartups.walk")
    data[ATS + ".5.4.5.1.5.1"] = 1
    for kind in ("ats", "ups"):
        for item in measurements(kind, data):
            if not item.enum:
                continue
            entity = ApcUpsSensor(MagicMock(), "entry", item)
            if item.key in ("selected_source", "preferred_source"):
                assert entity.translation_key is None
                assert item.value(data) in entity.options
                continue
            states = translations[entity.translation_key]["state"]
            for option in entity.options:
                assert re.fullmatch(r"[a-z][a-z0-9_]*", option)
                assert option in states


async def test_reconfigure_retains_v1(hass, fake_snmp):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="AS0000000001",
        data={
            "host": "192.0.2.1",
            "port": 1161,
            "snmp_version": "v1",
            "community": "retained",
        },
    )
    entry.add_to_hass(hass)
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
        )
        assert result["data_schema"]({}) == {
            "host": "192.0.2.1",
            "port": 1161,
            "snmp_version": "v1",
        }
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.0.2.2"}
        )
        assert result["data_schema"]({}) == {"community": "retained"}
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["reason"] == "reconfigure_successful"
    assert entry.data["snmp_version"] == "v1"
    assert entry.data["community"] == "retained"
    assert entry.data["port"] == 1161


@pytest.mark.parametrize("source", ["reconfigure", "reauth"])
async def test_v3_blank_password_preserved(hass, fake_snmp, source):
    data = {
        "host": "192.0.2.1",
        "port": 161,
        "snmp_version": "v3",
        "username": "monitor",
        "auth_protocol": "SHA",
        "auth_password": "secret123",
        "priv_protocol": "AES",
        "priv_password": "private123",
    }
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, unique_id="AS0000000001", data=data
    )
    entry.add_to_hass(hass)
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": source, "entry_id": entry.entry_id},
            data=data if source == "reauth" else None,
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        fields = {key.schema: key for key in result["data_schema"].schema}
        for key in ("username", "auth_protocol", "priv_protocol"):
            assert fields[key].description["suggested_value"] == data[key]
        for key in ("auth_password", "priv_password"):
            assert not fields[key].description
            assert fields[key].default is __import__("voluptuous").UNDEFINED
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"username": "monitor", "auth_password": "", "priv_password": ""},
        )
        assert result["reason"] == source + "_successful"
    assert entry.data["auth_password"] == "secret123"
    assert entry.data["priv_password"] == "private123"


@pytest.mark.parametrize(
    "credentials,field,error",
    [
        ({"auth_password": "password1"}, "auth_protocol", "protocol_required"),
        ({"auth_protocol": "SHA"}, "auth_password", "password_required"),
        (
            {"auth_protocol": "SHA", "auth_password": "short"},
            "auth_password",
            "password_too_short",
        ),
        (
            {"priv_protocol": "AES", "priv_password": "password1"},
            "priv_protocol",
            "privacy_requires_auth",
        ),
        (
            {
                "auth_protocol": "SHA",
                "auth_password": "password1",
                "priv_password": "password2",
            },
            "priv_protocol",
            "protocol_required",
        ),
        (
            {
                "auth_protocol": "SHA",
                "auth_password": "password1",
                "priv_protocol": "AES",
            },
            "priv_password",
            "password_required",
        ),
        (
            {
                "auth_protocol": "SHA",
                "auth_password": "password1",
                "priv_protocol": "AES",
                "priv_password": "short",
            },
            "priv_password",
            "password_too_short",
        ),
    ],
)
async def test_v3_validation(hass, fake_snmp, credentials, field, error):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "localhost", "port": 161, "snmp_version": "v3"}
    )
    with patch.object(fake_snmp, "async_test_connection") as connect:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "typed", **credentials}
        )
        connect.assert_not_called()
    assert result["errors"][field] == error
    fields = {key.schema: key for key in result["data_schema"].schema}
    assert fields["username"].description["suggested_value"] == "typed"


async def test_failed_form_retains_input(hass, fake_snmp):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "bad host", "port": 1161, "snmp_version": "v1"}
    )
    fields = {key.schema: key for key in result["data_schema"].schema}
    assert fields["host"].default() == "bad host"
    assert fields["snmp_version"].default() == "v1"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "localhost"}
    )
    with patch.object(fake_snmp, "async_test_connection", side_effect=SnmpAuthError):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"community": "typed"}
        )
    assert result["data_schema"]({})["community"] == "typed"


async def test_late_entities_and_device_fallback(hass, fake_snmp):
    from custom_components.apc_ups_snmp.catalog import IDENTITY
    from custom_components.apc_ups_snmp.entity import ApcUpsEntity

    with patch.object(fake_snmp, "async_get_all_data", return_value={}):
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="My UPS",
            version=2,
            data={"host": "::1", "snmp_version": "v1"},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entity = ApcUpsEntity(coordinator, entry.entry_id)
    assert entity.device_info["name"] == "My UPS"
    assert entity.device_info["model"] == "Unknown"
    assert entity.device_info["configuration_url"] == "http://[::1]"
    raw = read_walk("smartups.walk")
    coordinator.async_set_updated_data(raw)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    ids = {item.unique_id for item in entities}
    for key in ("battery_capacity", "outlet_group_1", "on_battery"):
        assert f"{entry.entry_id}_{key}" in ids
    coordinator.async_set_updated_data(raw)
    await hass.async_block_till_done()
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == len(
        entities
    )
    raw.update({oid: None for oid in IDENTITY["ups"].values()})
    coordinator.async_set_updated_data(raw)
    assert entity.device_info["name"] == "My UPS"
    assert entity.device_info["model"] == "Unknown"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_construction_error_is_security_error(hass, fake_snmp):
    from custom_components.apc_ups_snmp.config_flow import ApcUpsSnmpConfigFlow

    flow = ApcUpsSnmpConfigFlow()
    flow._data = {"host": "localhost"}
    with patch.object(fake_snmp, "from_config", side_effect=ValueError("bad key")):
        assert await flow._test_connection() == "invalid_security"


@pytest.mark.parametrize("kind", ["ups", "ats"])
@pytest.mark.parametrize("title", ["", "Saved title"])
async def test_device_info_none_fallbacks(hass, fake_snmp, kind, title):
    from custom_components.apc_ups_snmp.catalog import IDENTITY
    from custom_components.apc_ups_snmp.coordinator import ApcUpsCoordinator
    from custom_components.apc_ups_snmp.entity import ApcUpsEntity

    entry = MockConfigEntry(domain=DOMAIN, title=title, data={})
    entry.add_to_hass(hass)
    coordinator = ApcUpsCoordinator(hass, {"host": "localhost", "device_type": kind})
    coordinator.data = {oid: None for oid in IDENTITY[kind].values()}
    entity = ApcUpsEntity(coordinator, entry.entry_id)
    assert entity.device_info["name"] == (title or f"APC {kind.upper()}")
    assert entity.device_info["model"] == "Unknown"
    # Device info is also safe when its config entry is no longer present.
    with patch.object(hass.config_entries, "async_get_entry", return_value=None):
        assert entity.device_info["name"] == f"APC {kind.upper()}"
    coordinator.close()


@pytest.mark.parametrize(
    "kind,fixture", [("ups", "smartups.walk"), ("ats", "ap4452a.walk")]
)
async def test_late_rows_and_none_values(hass, fake_snmp, kind, fixture):
    data = read_walk(fixture)
    if kind == "ups":
        scalar = UPS + ".2.3.1.0"
        binary = UPS + ".2.2.4.0"
        row = UPS + ".12.1.2.1.3.9"
        keys = ("battery_capacity", "replace_battery", "outlet_group_9")
    else:
        scalar = ATS + ".1.7.0"
        binary = ATS + ".5.1.3.0"
        row = ATS + ".5.4.3.1.4.9.1.1"
        keys = ("input_nominal_voltage", "redundancy_lost", "output_current_9_1_1")
    # Start with a known scalar and binary sensor explicitly unavailable.
    for oid in list(data):
        if (
            oid == scalar
            or (kind == "ups" and oid == UPS + ".2.2.1.0")
            or oid == binary
        ):
            data[oid] = None
    with patch.object(fake_snmp, "async_get_all_data", return_value=data):
        entry = MockConfigEntry(
            domain=DOMAIN,
            version=2,
            data={"host": "localhost", "device_type": kind},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)

    def ids():
        return {
            item.unique_id
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        }

    expected = {f"{entry.entry_id}_{key}" for key in keys}
    assert not expected.intersection(ids())
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.async_set_updated_data({**data, scalar: 1000, binary: 2, row: 1})
    await hass.async_block_till_done()
    assert expected <= ids()
    count = len(ids())
    coordinator.async_set_updated_data(data)
    await hass.async_block_till_done()
    coordinator.async_set_updated_data({**data, scalar: 1000, binary: 2, row: 2})
    await hass.async_block_till_done()
    assert len(ids()) == count
    assert await hass.config_entries.async_unload(entry.entry_id)


def test_security_error_translations():
    import json
    from pathlib import Path

    from custom_components.apc_ups_snmp.snmp_client import validate_v3

    errors = {"invalid_security"}
    for data in (
        {"auth_password": "password1"},
        {"auth_protocol": "SHA"},
        {"auth_protocol": "SHA", "auth_password": "short"},
        {"auth_protocol": "unknown", "auth_password": "password1"},
        {"priv_protocol": "AES", "priv_password": "password1"},
        {
            "auth_protocol": "SHA",
            "auth_password": "password1",
            "priv_password": "short",
        },
    ):
        errors.update(validate_v3(data).values())
    for filename in ("strings.json", "translations/en.json"):
        strings = json.loads(
            (Path("custom_components/apc_ups_snmp") / filename).read_text()
        )
        assert errors <= strings["config"]["error"].keys()


async def test_failed_v3_form_retains_nonsecret_input(hass, fake_snmp):
    import voluptuous as vol

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "::1", "port": 1161, "snmp_version": "v3"}
    )
    credentials = {
        "username": "typed",
        "auth_protocol": "SHA256",
        "auth_password": "password1",
        "priv_protocol": "AES256",
        "priv_password": "password2",
    }
    with patch.object(fake_snmp, "async_test_connection", side_effect=SnmpAuthError):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], credentials
        )
    assert result["errors"] == {"base": "invalid_auth"}
    fields = {key.schema: key for key in result["data_schema"].schema}
    for key in ("username", "auth_protocol", "priv_protocol"):
        assert fields[key].description["suggested_value"] == credentials[key]
    for key in ("auth_password", "priv_password"):
        assert fields[key].default is vol.UNDEFINED
        assert not fields[key].description
