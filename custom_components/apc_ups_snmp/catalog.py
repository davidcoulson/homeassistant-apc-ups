"""Read-only PowerNet measurements. OID suffixes and scales are MIB facts."""

from dataclasses import dataclass
from typing import Any

from .const import LAST_TRANSFER_CAUSE_MAP

UPS = ".1.3.6.1.4.1.318.1.1.1"
ATS = ".1.3.6.1.4.1.318.1.1.8"
IDENTITY = {
    "ups": {
        "model": UPS + ".1.1.1.0",
        "name": UPS + ".1.1.2.0",
        "firmware": UPS + ".1.2.1.0",
        "serial": UPS + ".1.2.3.0",
        "manufacture_date": UPS + ".1.2.2.0",
    },
    "ats": {
        "model": ATS + ".1.5.0",
        "name": ATS + ".4.1.0",
        "firmware": ATS + ".1.2.0",
        "serial": ATS + ".1.6.0",
        "manufacture_date": ATS + ".1.4.0",
    },
}


@dataclass(frozen=True)
class Measurement:
    """Ordered OID alternatives, each with its own scale."""

    key: str
    sources: tuple[tuple[str, float | None], ...]
    unit: str | None = None
    device_class: str | None = None
    enum: dict[int, str] | None = None
    diagnostic: bool = False
    name: str | None = None

    reject_negative: bool = False

    def value(self, data: dict[str, Any]) -> float | str | None:
        """Read the first supported alternative."""
        for oid, scale in self.sources:
            raw = data.get(oid)
            if (
                raw is None
                or raw == -1
                or (self.reject_negative and isinstance(raw, (float, int)) and raw < 0)
            ):
                continue
            if self.enum is not None:
                return self.enum.get(raw)
            if scale is None:
                return str(raw)
            return round(float(raw) * scale, 4)
        return None


def m(
    key: str,
    suffix: str,
    unit: str | None = None,
    dc: str | None = None,
    scale: float | None = 1,
    fallback: str | None = None,
    enum: dict[int, str] | None = None,
    diag: bool = False,
    root: str = UPS,
    name: str | None = None,
    reject_negative: bool = False,
    before: tuple[tuple[str, float | None], ...] = (),
    after: tuple[tuple[str, float | None], ...] = (),
) -> Measurement:
    """Build a scalar measurement."""
    sources = ((root + suffix, scale),)
    if fallback:
        sources += ((root + fallback, 1),)
    return Measurement(
        key, before + sources + after, unit, dc, enum, diag, name, reject_negative
    )


UPS_MEASUREMENTS = [
    m("battery_capacity", ".2.3.1.0", "%", "battery", 0.1, ".2.2.1.0"),
    m("battery_runtime", ".2.2.3.0", "min", "duration", 1 / 6000),
    m("battery_temperature", ".2.3.2.0", "°C", "temperature", 0.1, ".2.2.2.0"),
    m("battery_voltage", ".2.3.4.0", "V", "voltage", 0.1, ".2.2.8.0"),
    m("battery_current", ".2.3.5.0", "A", "current", 0.1, ".2.2.9.0"),
    m("battery_current_total", ".2.3.6.0", "A", "current", 0.1, diag=True),
    m(
        "battery_nominal_voltage",
        ".2.3.3.0",
        "V",
        "voltage",
        0.1,
        ".2.2.7.0",
        diag=True,
    ),
    m("battery_packs", ".2.2.5.0", diag=True),
    m("battery_bad_packs", ".2.2.6.0", diag=True),
    m("battery_last_replaced", ".2.1.3.0", scale=None, diag=True),
    m("battery_replace_date", ".2.2.21.0", scale=None, diag=True),
    m("time_on_battery", ".2.1.2.0", "s", "duration", 0.01, diag=True),
    m("input_voltage", ".3.3.1.0", "V", "voltage", 0.1, ".3.2.1.0"),
    m("input_max_voltage", ".3.3.2.0", "V", "voltage", 0.1, ".3.2.2.0", diag=True),
    m("input_min_voltage", ".3.3.3.0", "V", "voltage", 0.1, ".3.2.3.0", diag=True),
    m(
        "input_frequency",
        ".3.3.4.0",
        "Hz",
        "frequency",
        0.1,
        ".3.2.4.0",
        before=((UPS + ".9.2.2.1.4.1", 0.1),),
    ),
    m("input_transfer_high", ".5.2.2.0", "V", "voltage", diag=True),
    m("input_transfer_low", ".5.2.3.0", "V", "voltage", diag=True),
    m(
        "input_sensitivity",
        ".5.2.7.0",
        enum={1: "auto", 2: "low", 3: "medium", 4: "high"},
        diag=True,
    ),
    m("output_voltage", ".4.3.1.0", "V", "voltage", 0.1, ".4.2.1.0"),
    m(
        "output_frequency",
        ".4.3.2.0",
        "Hz",
        "frequency",
        0.1,
        ".4.2.2.0",
        before=((UPS + ".9.3.2.1.4.1", 0.1),),
    ),
    m("output_current", ".4.3.4.0", "A", "current", 0.1, ".4.2.4.0"),
    m("output_load", ".4.3.3.0", "%", scale=0.1, fallback=".4.2.3.0"),
    m("output_power", ".4.2.8.0", "W", "power"),
    m("apparent_power", ".4.2.9.0", "VA", "apparent_power", diag=True),
    m("output_efficiency", ".4.3.5.0", "%", scale=0.1, diag=True, reject_negative=True),
    m("output_energy", ".4.3.6.0", "kWh", "energy", 0.01),
    m("output_nominal_voltage", ".5.2.1.0", "V", "voltage", diag=True),
    m("nominal_power", ".1.3.6.1.2.1.33.1.9.6.0", "W", "power", diag=True, root=""),
    m(
        "nominal_apparent_power",
        ".1.2.9.0",
        "VA",
        "apparent_power",
        diag=True,
        after=((".1.3.6.1.2.1.33.1.9.5.0", 1), (UPS + ".4.2.6.0", 1000)),
    ),
    m(
        "self_test_result",
        ".7.2.3.0",
        enum={1: "ok", 2: "failed", 3: "invalid", 4: "in_progress"},
        diag=True,
    ),
    m("self_test_date", ".7.2.4.0", scale=None, diag=True),
    m(
        "calibration_result",
        ".7.2.6.0",
        enum={
            1: "ok",
            2: "insufficient_capacity",
            3: "in_progress",
            4: "refused",
            5: "cancelled",
            6: "pending",
        },
        diag=True,
    ),
    m("calibration_date", ".7.2.7.0", scale=None, diag=True),
    m("battery_restart_capacity", ".5.2.6.0", "%", diag=True),
    m("battery_runtime_low", ".5.2.8.0", "s", "duration", 0.01, diag=True),
    m("shutdown_delay", ".5.2.10.0", "s", "duration", 0.01, diag=True),
    m("startup_delay", ".5.2.9.0", "s", "duration", 0.01, diag=True),
    m("input_line_bads", ".3.1.1.0", diag=True),
    m("input_phases", ".9.2.2.1.2.1", diag=True),
    m("output_phases", ".9.3.2.1.2.1", diag=True),
    m(
        "ambient_temperature",
        ".1.3.6.1.4.1.318.1.1.2.1.1.0",
        "°C",
        "temperature",
        root="",
    ),
    m("ambient_humidity", ".1.3.6.1.4.1.318.1.1.2.1.2.0", "%", "humidity", root=""),
    m("output_nominal_frequency", ".4.2.7.0", "Hz", "frequency", diag=True),
    m(
        "ambient_temperature_high",
        ".1.3.6.1.4.1.318.1.1.10.1.2.2.1.3.1",
        "°C",
        "temperature",
        root="",
        diag=True,
    ),
    m(
        "ambient_temperature_low",
        ".1.3.6.1.4.1.318.1.1.10.1.2.2.1.4.1",
        "°C",
        "temperature",
        root="",
        diag=True,
    ),
    m(
        "ambient_humidity_high",
        ".1.3.6.1.4.1.318.1.1.10.1.2.2.1.6.1",
        "%",
        "humidity",
        root="",
        diag=True,
    ),
    m(
        "ambient_humidity_low",
        ".1.3.6.1.4.1.318.1.1.10.1.2.2.1.7.1",
        "%",
        "humidity",
        root="",
        diag=True,
    ),
]

# PowerNet phase-table column facts. All indexes are discovered from the table.
UPS_PHASE_COLUMNS = [
    ("input_phase_frequency", ".9.2.2.1.4.", "Hz", "frequency", 0.1),
    ("output_phase_frequency", ".9.3.2.1.4.", "Hz", "frequency", 0.1),
    ("input_phase_voltage", ".9.2.3.1.3.", "V", "voltage", 1),
    ("input_phase_max_voltage", ".9.2.3.1.4.", "V", "voltage", 1),
    ("input_phase_min_voltage", ".9.2.3.1.5.", "V", "voltage", 1),
    ("input_phase_current", ".9.2.3.1.6.", "A", "current", 0.1),
    ("output_phase_voltage", ".9.3.3.1.3.", "V", "voltage", 1),
    ("output_phase_current", ".9.3.3.1.6.", "A", "current", 0.1),
    ("output_phase_power", ".9.3.3.1.7.", "VA", "apparent_power", 1),
    ("output_phase_max_power", ".9.3.3.1.8.", "VA", "apparent_power", 1),
    ("output_phase_min_power", ".9.3.3.1.9.", "VA", "apparent_power", 1),
    ("output_phase_real_power", ".9.3.3.1.13.", "W", "power", 1),
    ("output_phase_real_load", ".9.3.3.1.16.", "%", None, 1),
    ("output_phase_load", ".9.3.3.1.10.", "%", None, 1),
    ("output_phase_max_load", ".9.3.3.1.11.", "%", None, 1),
    ("output_phase_min_load", ".9.3.3.1.12.", "%", None, 1),
]

POWER_WORDS = {
    2: "OL",
    3: "OB",
    4: "OL BOOST",
    5: "OFF",
    6: "OFF",
    7: "OFF",
    9: "BYPASS",
    10: "BYPASS",
    11: "OFF",
    12: "OL TRIM",
    13: "OL ECO",
    14: "OL",
    15: "OL",
    16: "BYPASS",
    17: "BYPASS",
    19: "OL",
    20: "OL ECO",
    21: "OL",
    22: "OL",
    24: "OL",
    25: "OL",
    28: "OL",
}


def status(data):
    """Combine independent NUT status flags."""
    if data.get(UPS + ".4.1.1.0") is None:
        return None
    words = POWER_WORDS.get(data[UPS + ".4.1.1.0"], "").split()
    if data.get(UPS + ".2.1.1.0") in (3, 4, 5):
        words.append("LB")
    if data.get(UPS + ".2.2.4.0") == 2:
        words.append("RB")
    if data.get(UPS + ".7.2.6.0") == 3:
        words.append("CAL")
    flags = str(data.get(UPS + ".11.1.1.0") or "")
    if (
        (len(flags) == 64 and flags[8] == "1")
        or (data.get(UPS + ".4.2.3.0") or 0) > 100
        or (data.get(UPS + ".4.3.3.0") or 0) > 1000
    ):
        words.append("OVER")
    return " ".join(words) or "unknown"


def measurements(device_type, data):
    """Discover supported table rows without relying on fixed row counts."""
    if device_type == "ups":
        result = list(UPS_MEASUREMENTS)
        result.append(m("manufacture_date", ".1.2.2.0", scale=None, diag=True))
        for key, prefix, unit, dc, scale in UPS_PHASE_COLUMNS:
            rows = [oid for oid in sorted(data) if oid.startswith(UPS + prefix)]
            for oid in rows:
                if oid.startswith(UPS + prefix):
                    index = oid.removeprefix(UPS + prefix)
                    result.append(
                        Measurement(
                            key + "_" + index.replace(".", "_"),
                            ((oid, scale),),
                            unit,
                            dc,
                            diagnostic="max" in key or "min" in key,
                            name=key.replace("_phase", "")
                            .replace("_", " ")
                            .capitalize()
                            + (
                                f" phase {rows.index(oid) + 1}" if len(rows) > 1 else ""
                            ),
                        )
                    )

        result.append(
            m(
                "last_transfer_cause",
                ".3.2.5.0",
                enum={
                    number: label.lower().replace(" ", "_")
                    for number, label in LAST_TRANSFER_CAUSE_MAP.items()
                },
                diag=True,
            )
        )
        prefix = UPS + ".12.1.2.1.3."
        for oid in data:
            if oid.startswith(prefix):
                index = oid.removeprefix(prefix)
                result.append(
                    m(
                        "outlet_group_" + index,
                        ".12.1.2.1.3." + index,
                        enum={
                            1: "on",
                            2: "off",
                            3: "unknown",
                        },
                        name=str(
                            data.get(UPS + ".12.1.2.1.2." + index)
                            or "Outlet group " + index
                        ),
                    )
                )
        return result
    result = [
        m("manufacture_date", ".1.4.0", scale=None, root=ATS, diag=True),
        m("input_nominal_voltage", ".1.7.0", "V", "voltage", root=ATS, diag=True),
        m("input_nominal_frequency", ".1.8.0", "Hz", "frequency", root=ATS, diag=True),
        m(
            "input_sensitivity",
            ".4.4.0",
            enum={1: "high", 2: "low"},
            root=ATS,
            diag=True,
        ),
    ]
    result.extend(
        [
            m(
                "front_panel",
                ".5.1.11.0",
                enum={1: "locked", 2: "unlocked"},
                root=ATS,
                diag=True,
            ),
            m(
                "phase_sync",
                ".5.1.14.0",
                enum={1: "in_sync", 2: "out_of_sync"},
                root=ATS,
                diag=True,
            ),
        ]
    )
    names = {
        i: str(data.get(ATS + ".5.3.2.1.6." + str(i)) or f"Source {'AB'[i - 1]}")
        for i in (1, 2)
    }
    for key, suffix in [
        ("selected_source", ".5.1.2.0"),
        ("preferred_source", ".4.2.0"),
    ]:
        result.append(
            m(
                key,
                suffix,
                enum={
                    1: names[1],
                    2: names[2],
                    **({3: "none"} if key == "preferred_source" else {}),
                },
                root=ATS,
            )
        )
    tables = [
        (".5.3.2.1.4.", "input_frequency", "Hz", "frequency", 1, None),
        (
            ".5.3.2.1.3.",
            "input_orientation",
            None,
            None,
            1,
            {
                1: "unknown",
                2: "single_phase",
                3: "split_phase",
                4: "three_phase_neutral",
                5: "three_phase",
            },
        ),
        (
            ".5.3.2.1.5.",
            "input_type",
            None,
            None,
            1,
            {1: "unknown", 2: "main", 3: "bypass"},
        ),
        (".5.3.3.1.4.", "input_max_voltage", "V", "voltage", 1, None),
        (".5.3.3.1.5.", "input_min_voltage", "V", "voltage", 1, None),
        (".5.3.3.1.6.", "input_current", "A", "current", 0.1, None),
        (".5.3.3.1.9.", "input_power", "VA", "apparent_power", 1, None),
        (".5.3.3.1.3.", "input_voltage", "V", "voltage", 1, None),
        (".5.4.2.1.4.", "output_frequency", "Hz", "frequency", 1, None),
        (".5.4.3.1.3.", "output_voltage", "V", "voltage", 1, None),
        (".5.4.3.1.4.", "output_current", "A", "current", 0.1, None),
        (".5.4.3.1.13.", "output_power", "VA", "apparent_power", 1, None),
        (".5.4.3.1.16.", "output_load", "%", None, 1, None),
        (".5.4.5.1.4.", "bank_current", "A", "current", 0.1, None),
        (
            ".5.4.5.1.5.",
            "bank_status",
            None,
            None,
            1,
            {1: "normal", 2: "low_load", 3: "near_overload", 4: "overload"},
        ),
        (".5.4.5.1.6.", "bank_voltage", "V", "voltage", 1, None),
        (".5.4.5.1.15.", "bank_power", "W", "power", 1, None),
    ]
    for prefix, key, unit, dc, scale, enum in tables:
        rows = [
            oid.removeprefix(ATS + prefix)
            for oid in sorted(data)
            if oid.startswith(ATS + prefix)
        ]
        for oid in sorted(data):
            if oid.startswith(ATS + prefix):
                index = oid.removeprefix(ATS + prefix)
                label = (
                    names.get(int(index.split(".")[0]), "Input")
                    if key.startswith("input")
                    else "Bank"
                    if key.startswith("bank")
                    else "Output"
                )
                result.append(
                    Measurement(
                        key + "_" + index.replace(".", "_"),
                        ((oid, scale),),
                        unit,
                        dc,
                        enum,
                        key in ("input_orientation", "input_type", "output_frequency"),
                        f"{label} {key.split('_', 1)[1].replace('_', ' ')}"
                        + (
                            " "
                            + ("bank " if key.startswith("bank") else "phase ")
                            + str(
                                [
                                    row
                                    for row in rows
                                    if not key.startswith("input")
                                    or row.split(".")[0] == index.split(".")[0]
                                ].index(index)
                                + 1
                            )
                            if len(
                                [
                                    row
                                    for row in rows
                                    if not key.startswith("input")
                                    or row.split(".")[0] == index.split(".")[0]
                                ]
                            )
                            > 1
                            else ""
                        ),
                    )
                )
    return result


# Each ATS status uses fail(1)/ok(2).
ATS_PROBLEMS = {
    "redundancy_lost": 3,
    "overcurrent": 4,
    "power_supply_5v": 5,
    "power_supply_24v": 6,
    "power_supply_source_b": 7,
    "power_supply_plus_12v": 8,
    "power_supply_minus_12v": 9,
    "switch_fault": 10,
    "source_a_fault": 12,
    "source_b_fault": 13,
    "output_fault": 15,
    "hardware_fault": 16,
    "comms_fault": 1,
    "power_supply_3v3": 17,
    "power_supply_1v0": 18,
    "boost_source_a": 19,
    "boost_source_b": 20,
}
