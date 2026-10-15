"""Transport bounds, exceptional values, and failure classification."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pysnmp.proto.rfc1902 import Integer32, OctetString
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


async def test_executor_request_closes_dispatcher():
    client = ApcSnmpClient("192.0.2.1", version="v1")
    engine = MagicMock()
    with (
        ThreadPoolExecutor(max_workers=1) as executor,
        patch(
            "custom_components.apc_ups_snmp.snmp_client._get_executor",
            return_value=executor,
        ),
        patch(
            "custom_components.apc_ups_snmp.snmp_client.SnmpEngine", return_value=engine
        ),
        patch(
            "custom_components.apc_ups_snmp.snmp_client.UdpTransportTarget.create",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.apc_ups_snmp.snmp_client.get_cmd",
            new=AsyncMock(
                return_value=(None, None, 0, [("1.2.3", Integer32(125))]),
            ),
        ) as get,
    ):
        assert await client.async_get(".1.2.3") == 125
        assert get.await_count == 1
        engine.close_dispatcher.assert_called_once()


async def test_v1_missing_oid_isolated(fake_snmp):
    client = fake_snmp("192.0.2.1", version="v1")
    result = await client.async_get_multiple([ATS + ".1.5.0", UPS + ".1.1.1.0"])
    assert result[ATS + ".1.5.0"] is None
    assert result[UPS + ".1.1.1.0"] == "Smart-UPS 1500"


def test_bit_flags_remain_text():
    flags = "000100001" + "0" * 55
    assert ApcSnmpClient("192.0.2.1")._parse_value(OctetString(flags)) == flags
