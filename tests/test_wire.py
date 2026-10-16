"""Exercise real pysnmp PDUs against a fixture responder on loopback only."""

import asyncio
import socket

import pytest
from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.entity import config, engine
from pysnmp.entity.rfc3413 import cmdrsp, context
from pysnmp.proto.rfc1902 import Integer32, ObjectName, OctetString, TimeTicks
from pysnmp.proto.rfc1905 import endOfMibView, noSuchInstance

from custom_components.apc_ups_snmp.catalog import ATS, IDENTITY, UPS
from custom_components.apc_ups_snmp.snmp_client import (
    ApcSnmpClient,
    SnmpAuthError,
    SnmpTimeoutError,
)

from .conftest import read_walk

pytestmark = pytest.mark.usefixtures("socket_enabled")


@pytest.fixture(params=[("smartups.walk", "ups"), ("ap4452a.walk", "ats")])
async def responder(request):
    fixture, kind = request.param
    snmp = engine.SnmpEngine()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    transport = udp.UdpTransport().open_server_mode(sock=sock)
    config.add_transport(snmp, udp.DOMAIN_NAME, transport)
    config.add_v1_system(snmp, "fixture", "public")
    config.add_v3_user(
        snmp,
        "monitor",
        config.USM_AUTH_HMAC96_SHA,
        "authpass123",
        config.USM_PRIV_CFB128_AES,
        "privpass123",
    )
    for model, user, level in (
        (1, "fixture", "noAuthNoPriv"),
        (2, "fixture", "noAuthNoPriv"),
        (3, "monitor", "authPriv"),
    ):
        config.add_vacm_user(snmp, model, user, level, (1, 3, 6))
    data = {
        ObjectName(oid.strip(".")): (
            TimeTicks(value) if value > 2147483647 else Integer32(value)
        )
        if isinstance(value, int)
        else OctetString(value)
        for oid, value in read_walk(fixture).items()
    }
    ordered = sorted(data)

    class Instrumentation:
        def read_variables(self, *binds, **kwargs):
            return [(oid, data.get(oid, noSuchInstance)) for oid, _ in binds]

        def read_next_variables(self, *binds, **kwargs):
            result = []
            for oid, _ in binds:
                following = next((key for key in ordered if key > oid), None)
                result.append(
                    (following, data[following])
                    if following is not None
                    else (oid, endOfMibView)
                )
            return result

    ctx = context.SnmpContext(snmp)
    ctx.unregister_context_name(b"")
    ctx.register_context_name(b"", Instrumentation())
    handlers = [
        cls(snmp, ctx)
        for cls in (
            cmdrsp.GetCommandResponder,
            cmdrsp.NextCommandResponder,
            cmdrsp.BulkCommandResponder,
        )
    ]
    await transport._lport
    yield port, kind
    for handler in handlers:
        handler.close(snmp)
    snmp.close_dispatcher()
    await asyncio.sleep(0)


async def close(client):
    client.close()
    if client._executor:
        await asyncio.to_thread(client._executor.shutdown, wait=True)


@pytest.mark.parametrize("version", ["v1", "v2c", "v3"])
async def test_real_poll(responder, version):
    port, kind = responder
    client = ApcSnmpClient(
        "127.0.0.1",
        port,
        version,
        community="public",
        username="monitor",
        auth_protocol="SHA",
        auth_password="authpass123",
        priv_protocol="AES",
        priv_password="privpass123",
        timeout=1,
    )
    try:
        assert await client.async_detect_device() == kind
        result = await client.async_get_all_data()
        assert result[IDENTITY[kind]["model"]] is not None
        root = UPS + ".12.1.2" if kind == "ups" else ATS + ".5.4.3"
        assert any(oid.startswith(root + ".") for oid in result)
        assert await client.async_get(".1.3.6.1.4.1.318.999.0") is None
        assert await client.async_walk(".1.3.6.1.4.1.999999") == {}
        # A bulk response contains several rows, not nested varbind lists.
        rows, error = await client._request([root], walk=True)
        assert not error
        assert len(rows) > 1 if version != "v1" else len(rows) == 1
    finally:
        await close(client)


async def test_real_wrong_password(responder):
    port, _ = responder
    client = ApcSnmpClient(
        "127.0.0.1",
        port,
        "v3",
        username="monitor",
        auth_protocol="SHA",
        auth_password="wrongpass123",
        priv_protocol="AES",
        priv_password="privpass123",
        timeout=1,
    )
    try:
        with pytest.raises(SnmpAuthError):
            await client.async_get(UPS + ".1.1.1.0")
    finally:
        await close(client)


async def test_real_closed_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    client = ApcSnmpClient("127.0.0.1", port, timeout=0.1)
    try:
        with pytest.raises(SnmpTimeoutError):
            await client.async_get(UPS + ".1.1.1.0")
        assert client._target is None
        assert client._engine is not None
    finally:
        await close(client)


async def test_real_v3_construction_error(hass):
    """USM validates username size when building the request, after UsmUserData."""
    from custom_components.apc_ups_snmp.config_flow import ApcUpsSnmpConfigFlow

    flow = ApcUpsSnmpConfigFlow()
    flow._data = {
        "host": "127.0.0.1",
        "snmp_version": "v3",
        "username": "x" * 33,
        "auth_protocol": "SHA",
        "auth_password": "password1",
    }
    assert await flow._test_connection() == {"base": "invalid_security"}
