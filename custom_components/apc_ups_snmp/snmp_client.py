"""SNMP client for APC UPS devices."""

from __future__ import annotations

import asyncio
import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    get_cmd,
    next_cmd,
    usm3DESEDEPrivProtocol,
    usmAesCfb128Protocol,
    usmAesCfb192Protocol,
    usmAesCfb256Protocol,
    usmDESPrivProtocol,
    usmHMAC128SHA224AuthProtocol,
    usmHMAC192SHA256AuthProtocol,
    usmHMAC256SHA384AuthProtocol,
    usmHMAC384SHA512AuthProtocol,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
)

# Use async pysnmp API but run it in a thread with its own event loop
# to avoid blocking the Home Assistant event loop
from pysnmp.proto.rfc1902 import OctetString
from pysnmp.proto.rfc1905 import EndOfMibView, NoSuchInstance, NoSuchObject

from .catalog import ATS, IDENTITY, UPS, UPS_MEASUREMENTS
from .const import (
    AUTH_PROTOCOL_MD5,
    AUTH_PROTOCOL_SHA,
    AUTH_PROTOCOL_SHA224,
    AUTH_PROTOCOL_SHA256,
    AUTH_PROTOCOL_SHA384,
    AUTH_PROTOCOL_SHA512,
    DEFAULT_TIMEOUT,
    PRIV_PROTOCOL_3DES,
    PRIV_PROTOCOL_AES,
    PRIV_PROTOCOL_AES192,
    PRIV_PROTOCOL_AES256,
    PRIV_PROTOCOL_DES,
    ApcOid,
)

_LOGGER = logging.getLogger(__name__)

# Thread pool executor for running SNMP operations
# Limited to 4 workers to prevent resource exhaustion
_EXECUTOR: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    """Get or create the thread pool executor."""
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="snmp_")
    return _EXECUTOR


def shutdown_executor() -> None:
    """Shutdown the thread pool executor.

    Called automatically at interpreter exit or can be called manually
    when the integration is unloaded.
    """
    global _EXECUTOR
    if _EXECUTOR is not None:
        _EXECUTOR.shutdown(wait=False)
        _EXECUTOR = None


# Register cleanup at interpreter exit
atexit.register(shutdown_executor)


class SnmpError(Exception):
    """Base exception for SNMP errors."""


class SnmpConnectionError(SnmpError):
    """Exception for SNMP connection errors."""


class SnmpTimeoutError(SnmpError):
    """Exception for SNMP timeout errors."""


class SnmpAuthError(SnmpError):
    """Exception for SNMP authentication errors."""


# Mapping of auth protocol names to pysnmp protocol objects
AUTH_PROTOCOL_MAP = {
    AUTH_PROTOCOL_MD5: usmHMACMD5AuthProtocol,
    AUTH_PROTOCOL_SHA: usmHMACSHAAuthProtocol,
    AUTH_PROTOCOL_SHA224: usmHMAC128SHA224AuthProtocol,
    AUTH_PROTOCOL_SHA256: usmHMAC192SHA256AuthProtocol,
    AUTH_PROTOCOL_SHA384: usmHMAC256SHA384AuthProtocol,
    AUTH_PROTOCOL_SHA512: usmHMAC384SHA512AuthProtocol,
}

# Mapping of privacy protocol names to pysnmp protocol objects
PRIV_PROTOCOL_MAP = {
    PRIV_PROTOCOL_DES: usmDESPrivProtocol,
    PRIV_PROTOCOL_3DES: usm3DESEDEPrivProtocol,
    PRIV_PROTOCOL_AES: usmAesCfb128Protocol,
    PRIV_PROTOCOL_AES192: usmAesCfb192Protocol,
    PRIV_PROTOCOL_AES256: usmAesCfb256Protocol,
}


class ApcSnmpClient:
    """SNMP client for communicating with APC UPS devices."""

    def __init__(
        self,
        host: str,
        port: int = 161,
        version: str = "v2c",
        community: str | None = None,
        username: str | None = None,
        auth_protocol: str | None = None,
        auth_password: str | None = None,
        priv_protocol: str | None = None,
        priv_password: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the SNMP client.

        Args:
            host: IP address or hostname of the UPS.
            port: SNMP port (default 161).
            version: SNMP version ("v2c" or "v3").
            community: Community string for SNMP v2c.
            username: Username for SNMP v3.
            auth_protocol: Authentication protocol for SNMP v3.
            auth_password: Authentication password for SNMP v3.
            priv_protocol: Privacy protocol for SNMP v3.
            priv_password: Privacy password for SNMP v3.
            timeout: Request timeout in seconds.
        """
        self.host = host
        self.port = port
        self.version = version
        self.community = community
        self.username = username
        self.auth_protocol = auth_protocol
        self.auth_password = auth_password
        self.priv_protocol = priv_protocol
        self.priv_password = priv_password
        self.timeout = timeout

    def _get_auth_data(self) -> CommunityData | UsmUserData:
        """Get the authentication data based on SNMP version."""
        if self.version in ("v1", "v2c"):
            return CommunityData(
                self.community or "public", mpModel=0 if self.version == "v1" else 1
            )

        # SNMP v3
        auth_proto = None
        priv_proto = None

        if self.auth_protocol:
            auth_proto = AUTH_PROTOCOL_MAP.get(self.auth_protocol)

        if self.priv_protocol:
            priv_proto = PRIV_PROTOCOL_MAP.get(self.priv_protocol)

        return UsmUserData(
            userName=self.username or "",
            authKey=self.auth_password,
            privKey=self.priv_password,
            authProtocol=auth_proto,
            privProtocol=priv_proto,
        )

    def _run_snmp_in_thread(self, coro_func):
        """Run an async SNMP operation in a thread with its own event loop.

        This is necessary because pysnmp does blocking I/O (file operations
        for MIB loading, DNS resolution, etc.) that would block the Home
        Assistant event loop.
        """

        def run_coro():
            return asyncio.run(coro_func())

        return run_coro

    @staticmethod
    def _check_error(indication, status):
        """Classify transport and authorization failures."""
        message = " ".join(str(value) for value in (indication, status) if value)
        lowered = message.lower()
        if any(
            word in lowered
            for word in ("auth", "unknownusername", "digest", "decryption")
        ):
            raise SnmpAuthError(message)
        if indication:
            if "timeout" in lowered or "timed out" in lowered:
                raise SnmpTimeoutError(message)
            raise SnmpConnectionError(message)

    async def _request(self, oids, walk=False):
        """Run one bounded read in the dedicated executor."""

        async def operation():
            engine = SnmpEngine()
            try:
                target = await UdpTransportTarget.create(
                    (self.host, self.port), timeout=self.timeout, retries=1
                )
                command = next_cmd if walk else get_cmd
                indication, status, index, binds = await command(
                    engine,
                    self._get_auth_data(),
                    target,
                    ContextData(),
                    *(ObjectType(ObjectIdentity(oid)) for oid in oids),
                    lookupMib=False,
                )
                self._check_error(indication, status)
                if status:
                    return {}, int(index or -1)
                return {
                    "." + str(oid).lstrip("."): self._parse_value(value)
                    for oid, value in binds
                }, 0
            except SnmpError:
                raise
            except Exception as err:
                raise SnmpConnectionError(str(err)) from err
            finally:
                engine.close_dispatcher()

        return await asyncio.get_running_loop().run_in_executor(
            _get_executor(), self._run_snmp_in_thread(operation)
        )

    async def _async_execute_get(self, oid):
        return (await self.async_get_multiple([oid])).get(oid)

    async def async_walk(self, root):
        """GETNEXT works for all versions; stop at subtree/end/nonprogress."""
        result = {}
        cursor = root
        for _ in range(10000):
            values, error = await self._request([cursor], walk=True)
            if error or not values:
                break
            oid, value = next(iter(values.items()))
            if not oid.startswith(root + ".") or tuple(
                map(int, oid.strip(".").split("."))
            ) <= tuple(map(int, cursor.strip(".").split("."))):
                break
            # Unsupported cells still advance the cursor.
            result[oid] = value
            cursor = oid
        return result

    def _parse_value(self, value: Any) -> Any:
        """Parse an SNMP value to a Python type."""
        if value is None or isinstance(
            value, (NoSuchObject, NoSuchInstance, EndOfMibView)
        ):
            return None
        if isinstance(value, (int, float)) and value == -1:
            return None

        # Check for noSuchObject or noSuchInstance
        if hasattr(value, "prettyPrint"):
            pretty_value = value.prettyPrint()
            # Case-insensitive check for "no such" (handles "noSuchObject", "No Such Object", etc.)
            if any(
                word in pretty_value.lower().replace(" ", "")
                for word in ("nosuch", "endofmib")
            ):
                return None

        if isinstance(value, OctetString):
            return value.prettyPrint()

        # Try to get the Python value
        if hasattr(value, "prettyPrint"):
            str_value = value.prettyPrint()

            # Try integer first
            try:
                return None if int(str_value) == -1 else int(str_value)
            except ValueError:
                pass

            # Try float
            try:
                return float(str_value)
            except ValueError:
                pass

            # Return as string
            return str_value

        return value

    async def async_detect_device(self):
        """Probe identity; reject unrelated SNMP agents."""
        if await self.async_get(IDENTITY["ats"]["model"]) is not None:
            self.device_type = "ats"
        elif await self.async_get(IDENTITY["ups"]["model"]) is not None:
            self.device_type = "ups"
        else:
            raise SnmpConnectionError("No supported APC UPS or ATS identity")
        return self.device_type

    async def async_test_connection(self):
        await self.async_detect_device()
        return True

    async def async_get(self, oid):
        return await self._async_execute_get(oid)

    async def async_get_multiple(self, oids):
        """Limit PDUs to 20 bindings, isolate v1 noSuchName failures."""
        result = {}
        for start in range(0, len(oids), 20):
            pending = list(oids[start : start + 20])
            while pending:
                values, error = await self._request(pending)
                if not error:
                    result.update(values)
                    break
                # v1 rejects the entire PDU for a missing OID.
                if 0 < error <= len(pending):
                    result[pending.pop(error - 1)] = None
                elif len(pending) > 1:
                    for oid in pending:
                        result[oid] = await self.async_get(oid)
                    break
                else:
                    result[pending[0]] = None
                    break
        return result

    async def async_get_identity(self):
        kind = getattr(self, "device_type", None) or await self.async_detect_device()
        mapping = IDENTITY[kind]
        data = await self.async_get_multiple(list(mapping.values()))
        return {key: data.get(oid) for key, oid in mapping.items()}

    async def async_get_all_data(self):
        kind = getattr(self, "device_type", "ups")
        oids = list(IDENTITY[kind].values())
        if kind == "ats":
            oids += [ATS + f".5.1.{i}.0" for i in range(1, 23)]
            oids += [ATS + s for s in (".1.7.0", ".1.8.0", ".4.2.0", ".4.4.0")]
            roots = [
                ATS + ".5.3.2",
                ATS + ".5.3.3",
                ATS + ".5.4.2",
                ATS + ".5.4.3",
                ATS + ".5.4.5",
            ]
        else:
            oids += [oid for item in UPS_MEASUREMENTS for oid, _ in item.sources]
            oids += ApcOid.binary_sensor_oids() + [
                ApcOid.LAST_TRANSFER_CAUSE,
                UPS + ".11.1.1.0",
            ]
            roots = [UPS + ".12.1.2", UPS + ".9.2", UPS + ".9.3"]
        data = await self.async_get_multiple(list(dict.fromkeys(oids)))
        for root in roots:
            data.update(await self.async_walk(root))
        return data

    def close(self):
        """Requests own and close their dispatchers."""
