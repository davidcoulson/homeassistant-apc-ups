"""Transport bounds, exceptional values, and failure classification."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pysnmp.proto.rfc1902 import Gauge32, Integer32, OctetString, TimeTicks
from pysnmp.proto.rfc1905 import EndOfMibView, NoSuchInstance, NoSuchObject

from custom_components.apc_ups_snmp.catalog import ATS, UPS
from custom_components.apc_ups_snmp.snmp_client import (
    ApcSnmpClient,
    SnmpAuthError,
    SnmpConnectionError,
    SnmpTimeoutError,
)


@pytest.mark.parametrize("version,model", [("v1", 0), ("v2c", 1)])
def test_community_version(version, model):
    assert (
        ApcSnmpClient("192.0.2.1", version=version)
        ._get_auth_data()
        .message_processing_model
        == model
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        (Integer32(-1), None),
        (Integer32(120), 120),
        (Gauge32(125), 125),
        (TimeTicks(180000), 180000),
        (OctetString("01/15/2024"), "01/15/2024"),
        (NoSuchObject(), None),
        (NoSuchInstance(), None),
        (EndOfMibView(), None),
        (-1, None),
    ],
)
def test_parse(raw, expected):
    assert ApcSnmpClient("192.0.2.1")._parse_value(raw) == expected


@pytest.mark.parametrize(
    "indication,status,error",
    [
        ("No SNMP response received before timeout", None, SnmpTimeoutError),
        ("Wrong SNMP PDU digest", "authorizationError", SnmpAuthError),
        (None, "authorizationError", SnmpAuthError),
        ("unknownUserName", None, SnmpAuthError),
        ("connection refused", None, SnmpConnectionError),
    ],
)
def test_errors(indication, status, error):
    with pytest.raises(error):
        ApcSnmpClient._check_error(indication, status)


async def test_detection(fake_snmp):
    for fixture, kind in [("ap4452a.walk", "ats"), ("smartups.walk", "ups")]:
        fake_snmp.fixture = fixture
        client = fake_snmp("192.0.2.1", version="v1")
        assert await client.async_detect_device() == kind
        identity = await client.async_get_identity()
        assert identity["serial"].startswith("5A" if kind == "ats" else "AS")
    with (
        patch.object(client, "async_get", return_value=None),
        pytest.raises(SnmpConnectionError),
    ):
        await client.async_detect_device()


async def test_walk_stops_on_nonprogress():
    client = ApcSnmpClient("192.0.2.1", version="v1")
    root = UPS + ".12.1.2"
    with patch.object(
        client, "_request", new=AsyncMock(return_value=({root + ".1": 1}, 0))
    ) as request:
        result = await client.async_walk(root)
        assert result == {root + ".1": 1}
        assert request.await_count == 2


async def test_walk_subtree_boundary():
    client = ApcSnmpClient("192.0.2.1")
    with patch.object(client, "_request", return_value=({ATS + ".99": 1}, 0)):
        assert await client.async_walk(UPS) == {}


async def test_too_big_splits():
    client = ApcSnmpClient("192.0.2.1")

    async def request(oids, walk=False):
        if len(oids) > 1:
            return {}, -1
        return {oids[0]: 42}, 0

    with patch.object(client, "_request", side_effect=request):
        assert await client.async_get_multiple([".1.1", ".1.2"]) == {
            ".1.1": 42,
            ".1.2": 42,
        }


async def test_executor_reuses_engine_and_loop():
    import asyncio
    import threading

    client = ApcSnmpClient("192.0.2.1", version="v3")
    engine = MagicMock()
    owners = []

    async def get(*args, **kwargs):
        owners.append((threading.get_ident(), asyncio.get_running_loop()))
        return None, None, 0, [("1.2.3", Integer32(125))]

    with (
        patch(
            "custom_components.apc_ups_snmp.snmp_client.SnmpEngine", return_value=engine
        ) as factory,
        patch(
            "custom_components.apc_ups_snmp.snmp_client.UdpTransportTarget.create",
            new=AsyncMock(),
        ) as target,
        patch("custom_components.apc_ups_snmp.snmp_client.get_cmd", side_effect=get),
    ):
        try:
            assert await client.async_get(".1.2.3") == 125
            assert await client.async_get(".1.2.3") == 125
            assert owners[0] == owners[1]
            assert owners[0][0] != threading.get_ident()
            factory.assert_called_once()
            target.assert_awaited_once()
            engine.close_dispatcher.assert_not_called()
        finally:
            client.close()
            await asyncio.to_thread(client._executor.shutdown, wait=True)
        engine.close_dispatcher.assert_called_once()
        assert owners[0][1].is_closed()


async def test_v1_missing_oid_isolated(fake_snmp):
    client = fake_snmp("192.0.2.1", version="v1")
    result = await client.async_get_multiple([ATS + ".1.5.0", UPS + ".1.1.1.0"])
    assert result[ATS + ".1.5.0"] is None
    assert result[UPS + ".1.1.1.0"] == "Smart-UPS 1500"


def test_bit_flags_remain_text():
    flags = "000100001" + "0" * 55
    assert ApcSnmpClient("192.0.2.1")._parse_value(OctetString(flags)) == flags


@pytest.mark.parametrize(
    "version,command", [("v1", "next_cmd"), ("v2c", "bulk_cmd"), ("v3", "bulk_cmd")]
)
async def test_walk_command(version, command):
    import asyncio

    client = ApcSnmpClient("192.0.2.1", version=version)
    root = UPS + ".12.1.2"
    with (
        patch("custom_components.apc_ups_snmp.snmp_client.SnmpEngine"),
        patch(
            "custom_components.apc_ups_snmp.snmp_client.UdpTransportTarget.create",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.apc_ups_snmp.snmp_client." + command,
            new=AsyncMock(
                return_value=(
                    None,
                    None,
                    0,
                    [(root + ".1", Integer32(1)), (ATS, Integer32(2))],
                )
            ),
        ) as request,
    ):
        try:
            assert await client.async_walk(root) == {root + ".1": 1}
            if version != "v1":
                assert request.call_args.args[4:6] == (0, 20)
        finally:
            client.close()
            await asyncio.to_thread(client._executor.shutdown, wait=True)


async def test_table_cache(fake_snmp):
    from unittest.mock import patch

    client = fake_snmp("192.0.2.1")
    client.device_type = "ats"
    client.fixture = "ap4452a.walk"
    with patch(
        "custom_components.apc_ups_snmp.snmp_client.time.monotonic", return_value=10000
    ) as now:
        first = await client.async_get_all_data()
        assert any(walk for _, walk in client.calls)
        client.calls.clear()
        second = await client.async_get_all_data()
        assert {oid: value for oid, value in first.items() if value is not None} == {
            oid: value for oid, value in second.items() if value is not None
        }
        assert not any(walk for _, walk in client.calls)
        now.return_value += 3600
        await client.async_get_all_data()
        assert any(walk for _, walk in client.calls)
        client.calls.clear()
        # A vanished known cell triggers rediscovery without waiting an hour.
        with patch.object(
            client,
            "async_get_multiple",
            return_value={oid: None for oid in client._table_oids},
        ):
            await client.async_get_all_data()
        assert any(walk for _, walk in client.calls)


def test_timeticks_scaling():
    from custom_components.apc_ups_snmp.catalog import UPS_MEASUREMENTS

    client = ApcSnmpClient("192.0.2.1")
    data = {
        UPS + ".2.2.3.0": client._parse_value(TimeTicks(180000)),
        UPS + ".2.1.2.0": client._parse_value(TimeTicks(12300)),
    }
    values = {item.key: item.value(data) for item in UPS_MEASUREMENTS}
    assert values["battery_runtime"] == 30
    assert values["time_on_battery"] == 123
