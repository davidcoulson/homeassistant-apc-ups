"""SNMP client for APC UPS devices."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pyasn1.error import PyAsn1Error
from pysnmp.error import PySnmpError
from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    Udp6TransportTarget,
    UdpTransportTarget,
    UsmUserData,
    bulk_cmd,
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
_MISSING = object()


class SnmpConfigError(ValueError):
    """Invalid local SNMP security settings."""

    def __init__(self, errors):
        self.errors = errors
        super().__init__(str(errors))


def validate_v3(data):
    """Require explicit, paired protocols and sufficiently long keys."""
    errors = {}
    for prefix in ("auth", "priv"):
        protocol = data.get(prefix + "_protocol")
        password = data.get(prefix + "_password")
        if password and not protocol:
            errors[prefix + "_protocol"] = "protocol_required"
        if protocol and not password:
            errors[prefix + "_password"] = "password_required"
        if password and len(password) < 8:
            errors[prefix + "_password"] = "password_too_short"
        mapping = AUTH_PROTOCOL_MAP if prefix == "auth" else PRIV_PROTOCOL_MAP
        if protocol and protocol not in mapping:
            errors[prefix + "_protocol"] = "invalid_protocol"
    if (data.get("priv_protocol") or data.get("priv_password")) and not (
        data.get("auth_protocol") and data.get("auth_password")
    ):
        errors["priv_protocol"] = "privacy_requires_auth"
    return errors


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
        self._executor = None
        self._loop = None
        self._engine = None
        self._target = None
        self._auth_data = None
        self._closed = False
        self._table_oids = None
        self._discovered_at = 0.0
        self._hourly_discovered_at = 0.0
        self._missing_scalars = set()
        self._missing_cells = set()

    @classmethod
    def from_config(cls, data):
        """Build a client consistently from entry or flow data."""
        keys = (
            "host",
            "port",
            "community",
            "username",
            "auth_protocol",
            "auth_password",
            "priv_protocol",
            "priv_password",
        )
        return cls(
            version=data.get("snmp_version", "v2c"),
            **{key: data[key] for key in keys if key in data},
        )

    def _get_auth_data(self) -> CommunityData | UsmUserData:
        """Get the authentication data based on SNMP version."""
        if self.version in ("v1", "v2c"):
            return CommunityData(
                self.community or "public", mpModel=0 if self.version == "v1" else 1
            )

        errors = validate_v3(vars(self))
        if errors:
            raise SnmpConfigError(errors)

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
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
            return self._loop.run_until_complete(coro_func())

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
            try:
                if self._engine is None:
                    self._engine = SnmpEngine()
                if self._target is None:
                    try:
                        ipv6 = ipaddress.ip_address(self.host).version == 6
                    except ValueError:
                        ipv6 = False
                    target_type = Udp6TransportTarget if ipv6 else UdpTransportTarget
                    self._target = await target_type.create(
                        (self.host, self.port), timeout=self.timeout, retries=1
                    )
                if self._auth_data is None:
                    self._auth_data = self._get_auth_data()
                command = (
                    (next_cmd if self.version == "v1" else bulk_cmd)
                    if walk
                    else get_cmd
                )
                bulk_args = (0, 20) if walk and self.version != "v1" else ()
                indication, status, index, binds = await command(
                    self._engine,
                    self._auth_data,
                    self._target,
                    ContextData(),
                    *bulk_args,
                    *(ObjectType(ObjectIdentity(oid)) for oid in oids),
                    lookupMib=False,
                )
                self._check_error(indication, status)
                if status:
                    return {}, int(index or -1) if int(status) == 2 else -1
                values = {}
                for oid, value in binds:
                    if walk and isinstance(value, EndOfMibView):
                        break
                    values["." + str(oid).lstrip(".")] = (
                        _MISSING
                        if isinstance(
                            value, (NoSuchObject, NoSuchInstance, EndOfMibView)
                        )
                        else self._parse_value(value)
                    )
                return values, 0
            except (SnmpTimeoutError, SnmpConnectionError):
                self._target = None
                raise
            except (SnmpError, SnmpConfigError):
                raise
            except (PySnmpError, PyAsn1Error, ValueError, TypeError) as err:
                raise SnmpConfigError({"base": "invalid_security"}) from err
            except Exception as err:
                self._target = None
                raise SnmpConnectionError(str(err)) from err

        if self._closed:
            raise SnmpConnectionError("Client is closed")
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="apc_snmp"
            )
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, self._run_snmp_in_thread(operation)
        )

    async def _async_execute_get(self, oid):
        return (await self.async_get_multiple([oid])).get(oid)

    async def async_walk(self, root):
        """Discover cells with GETBULK (GETNEXT for v1), stopping at boundaries."""
        result = {}
        cursor = root
        for _ in range(10000):
            values, error = await self._request([cursor], walk=True)
            if error or not values:
                break
            for oid, value in values.items():
                if value is _MISSING:
                    return result
                if not oid.startswith(root + ".") or tuple(
                    map(int, oid.strip(".").split("."))
                ) <= tuple(map(int, cursor.strip(".").split("."))):
                    return result
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
        result = {oid: None for oid in oids if oid in self._missing_scalars}
        oids = [oid for oid in oids if oid not in self._missing_scalars]
        for start in range(0, len(oids), 20):
            pending = list(oids[start : start + 20])
            while pending:
                values, error = await self._request(pending)
                if not error:
                    for oid, value in values.items():
                        if value is _MISSING:
                            self._remember_missing(oid)
                            value = None
                        result[oid] = value
                    break
                # v1 rejects the entire PDU for a missing OID.
                if 0 < error <= len(pending):
                    oid = pending.pop(error - 1)
                    self._remember_missing(oid)
                    result[oid] = None
                elif len(pending) > 1:
                    for oid in pending:
                        result[oid] = await self.async_get(oid)
                    break
                else:
                    result[pending[0]] = None
                    break
        return result

    def _remember_missing(self, oid):
        if oid in (self._table_oids or ()):
            self._missing_cells.add(oid)
        else:
            self._missing_scalars.add(oid)

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
        hourly = (
            self._table_oids is None
            or time.monotonic() - self._hourly_discovered_at >= 3600
        )
        discover = hourly
        if hourly:
            self._missing_scalars.clear()
        self._missing_cells.clear()
        data = await self.async_get_multiple(
            list(dict.fromkeys(oids + list(self._table_oids or ())))
        )
        if self._missing_cells and time.monotonic() - self._discovered_at >= 300:
            discover = True
        if discover:
            tables = {}
            for root in roots:
                tables.update(await self.async_walk(root))
            self._table_oids = tuple(tables)
            self._discovered_at = time.monotonic()
            if hourly:
                self._hourly_discovered_at = self._discovered_at
            data.update(tables)
        return data

    def close(self):
        """Queue dispatcher and loop cleanup on the client's owning thread."""
        if self._closed:
            return
        self._closed = True
        if self._executor is None:
            return

        def cleanup():
            if self._engine is not None:
                self._engine.close_dispatcher()
            if self._loop is not None:
                tasks = asyncio.all_tasks(self._loop)
                for task in tasks:
                    task.cancel()
                if tasks:
                    self._loop.run_until_complete(
                        asyncio.gather(*tasks, return_exceptions=True)
                    )
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                self._loop.close()

        self._executor.submit(cleanup)
        self._executor.shutdown(wait=False)
