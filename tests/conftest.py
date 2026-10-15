"""Fixture-backed SNMP reads for integration tests."""

from pathlib import Path
from typing import ClassVar

import pytest

from custom_components.apc_ups_snmp.snmp_client import _MISSING, ApcSnmpClient


def read_walk(name):
    data = {}
    for line in (Path(__file__).parent / "fixtures" / name).read_text().splitlines():
        if " = " not in line:
            continue
        oid, value = line.split(" = ", 1)
        kind, value = value.split(": ", 1)
        if kind == "STRING":
            data[oid] = value.strip('"')
        elif kind == "Timeticks":
            data[oid] = int(value.split(")")[0].strip("("))
        elif kind in ("INTEGER", "Gauge32", "Counter32"):
            data[oid] = int(value)
        else:
            data[oid] = value
    return data


class WalkClient(ApcSnmpClient):
    """Exercise production chunking/discovery/polling against a walk."""

    fixture = "smartups.walk"
    calls: ClassVar[list] = []

    async def _request(self, oids, walk=False):
        data = read_walk(self.fixture)
        self.calls.append((list(oids), walk))
        if walk:
            cursor = tuple(map(int, oids[0].strip(".").split(".")))
            for oid in sorted(
                data, key=lambda x: tuple(map(int, x.strip(".").split(".")))
            ):
                if tuple(map(int, oid.strip(".").split("."))) > cursor:
                    return {oid: None if data[oid] == -1 else data[oid]}, 0
            return {}, 0
        if self.version == "v1":
            for index, oid in enumerate(oids, 1):
                if oid not in data:
                    return {}, index
        return {
            oid: None if data.get(oid) == -1 else data.get(oid, _MISSING)
            for oid in oids
        }, 0


@pytest.fixture(autouse=True)
def enable_custom(enable_custom_integrations):
    """Enable this custom component."""


@pytest.fixture
def fake_snmp(monkeypatch):
    WalkClient.calls = []
    WalkClient.fixture = "smartups.walk"
    monkeypatch.setattr(
        "custom_components.apc_ups_snmp.config_flow.ApcSnmpClient", WalkClient
    )
    monkeypatch.setattr(
        "custom_components.apc_ups_snmp.coordinator.ApcSnmpClient", WalkClient
    )
    return WalkClient
