"""Constants for the APC UPS SNMP integration."""

from typing import Final

DOMAIN: Final = "apc_ups_snmp"
DEFAULT_PORT: Final = 161
DEFAULT_SCAN_INTERVAL: Final = 30  # seconds
MIN_SCAN_INTERVAL: Final = 10  # seconds
MAX_SCAN_INTERVAL: Final = 300  # seconds (5 minutes)
DEFAULT_TIMEOUT: Final = 5  # seconds

# SNMP versions
SNMP_VERSION_1: Final = "v1"
SNMP_VERSION_2C: Final = "v2c"
SNMP_VERSION_3: Final = "v3"

# SNMP v3 authentication protocols
AUTH_PROTOCOL_MD5: Final = "MD5"
AUTH_PROTOCOL_SHA: Final = "SHA"
AUTH_PROTOCOL_SHA224: Final = "SHA224"
AUTH_PROTOCOL_SHA256: Final = "SHA256"
AUTH_PROTOCOL_SHA384: Final = "SHA384"
AUTH_PROTOCOL_SHA512: Final = "SHA512"

AUTH_PROTOCOLS: Final = [
    AUTH_PROTOCOL_MD5,
    AUTH_PROTOCOL_SHA,
    AUTH_PROTOCOL_SHA224,
    AUTH_PROTOCOL_SHA256,
    AUTH_PROTOCOL_SHA384,
    AUTH_PROTOCOL_SHA512,
]

# SNMP v3 privacy protocols
PRIV_PROTOCOL_DES: Final = "DES"
PRIV_PROTOCOL_3DES: Final = "3DES"
PRIV_PROTOCOL_AES: Final = "AES"
PRIV_PROTOCOL_AES192: Final = "AES192"
PRIV_PROTOCOL_AES256: Final = "AES256"

PRIV_PROTOCOLS: Final = [
    PRIV_PROTOCOL_DES,
    PRIV_PROTOCOL_3DES,
    PRIV_PROTOCOL_AES,
    PRIV_PROTOCOL_AES192,
    PRIV_PROTOCOL_AES256,
]

# Configuration keys
CONF_COMMUNITY: Final = "community"
CONF_SNMP_VERSION: Final = "snmp_version"
CONF_AUTH_PROTOCOL: Final = "auth_protocol"
CONF_AUTH_PASSWORD: Final = "auth_password"
CONF_PRIV_PROTOCOL: Final = "priv_protocol"
CONF_PRIV_PASSWORD: Final = "priv_password"
CONF_SENSORS: Final = "sensors"


class ApcOid:
    """APC PowerNet MIB OIDs for UPS monitoring."""

    # Identity OIDs
    MODEL: Final = ".1.3.6.1.4.1.318.1.1.1.1.1.1.0"
    NAME: Final = ".1.3.6.1.4.1.318.1.1.1.1.1.2.0"
    FIRMWARE: Final = ".1.3.6.1.4.1.318.1.1.1.1.2.1.0"
    SERIAL: Final = ".1.3.6.1.4.1.318.1.1.1.1.2.3.0"
    MANUFACTURE_DATE: Final = ".1.3.6.1.4.1.318.1.1.1.1.2.2.0"

    # Battery OIDs
    BATTERY_STATUS: Final = ".1.3.6.1.4.1.318.1.1.1.2.1.1.0"
    TIME_ON_BATTERY: Final = ".1.3.6.1.4.1.318.1.1.1.2.1.2.0"
    BATTERY_CAPACITY: Final = ".1.3.6.1.4.1.318.1.1.1.2.2.1.0"
    BATTERY_TEMPERATURE: Final = ".1.3.6.1.4.1.318.1.1.1.2.2.2.0"
    BATTERY_RUNTIME: Final = ".1.3.6.1.4.1.318.1.1.1.2.2.3.0"
    BATTERY_REPLACE: Final = ".1.3.6.1.4.1.318.1.1.1.2.2.4.0"
    BATTERY_VOLTAGE: Final = ".1.3.6.1.4.1.318.1.1.1.2.2.8.0"
    BATTERY_CURRENT: Final = ".1.3.6.1.4.1.318.1.1.1.2.2.9.0"
    BATTERY_ACTUAL_VOLTAGE: Final = ".1.3.6.1.4.1.318.1.1.1.2.2.10.0"

    # Input OIDs
    INPUT_LINE_BADS: Final = ".1.3.6.1.4.1.318.1.1.1.3.1.1.0"
    INPUT_VOLTAGE: Final = ".1.3.6.1.4.1.318.1.1.1.3.2.1.0"
    INPUT_MAX_VOLTAGE: Final = ".1.3.6.1.4.1.318.1.1.1.3.2.2.0"
    INPUT_MIN_VOLTAGE: Final = ".1.3.6.1.4.1.318.1.1.1.3.2.3.0"
    INPUT_FREQUENCY: Final = ".1.3.6.1.4.1.318.1.1.1.3.2.4.0"
    LAST_TRANSFER_CAUSE: Final = ".1.3.6.1.4.1.318.1.1.1.3.2.5.0"
    INPUT_SENSITIVITY: Final = ".1.3.6.1.4.1.318.1.1.1.5.2.7.0"

    # Output OIDs
    OUTPUT_STATUS: Final = ".1.3.6.1.4.1.318.1.1.1.4.1.1.0"
    OUTPUT_VOLTAGE: Final = ".1.3.6.1.4.1.318.1.1.1.4.2.1.0"
    OUTPUT_FREQUENCY: Final = ".1.3.6.1.4.1.318.1.1.1.4.2.2.0"
    OUTPUT_LOAD: Final = ".1.3.6.1.4.1.318.1.1.1.4.2.3.0"
    OUTPUT_CURRENT: Final = ".1.3.6.1.4.1.318.1.1.1.4.2.4.0"
    OUTPUT_POWER: Final = ".1.3.6.1.4.1.318.1.1.1.4.2.8.0"

    # High-precision Output OIDs (values in tenths)
    # These provide better resolution than standard OIDs
    OUTPUT_VOLTAGE_HIGH_PREC: Final = ".1.3.6.1.4.1.318.1.1.1.4.3.1.0"
    OUTPUT_FREQUENCY_HIGH_PREC: Final = ".1.3.6.1.4.1.318.1.1.1.4.3.2.0"
    OUTPUT_LOAD_HIGH_PREC: Final = ".1.3.6.1.4.1.318.1.1.1.4.3.3.0"
    OUTPUT_CURRENT_HIGH_PREC: Final = ".1.3.6.1.4.1.318.1.1.1.4.3.4.0"
    OUTPUT_EFFICIENCY_HIGH_PREC: Final = ".1.3.6.1.4.1.318.1.1.1.4.3.5.0"
    OUTPUT_ENERGY_HIGH_PREC: Final = ".1.3.6.1.4.1.318.1.1.1.4.3.6.0"

    # Self-test OIDs
    SELF_TEST_RESULT: Final = ".1.3.6.1.4.1.318.1.1.1.7.2.3.0"
    SELF_TEST_DATE: Final = ".1.3.6.1.4.1.318.1.1.1.7.2.4.0"

    # Diagnostic OIDs
    DIAG_BATTERY_STATUS: Final = ".1.3.6.1.4.1.318.1.1.1.2.1.1.0"

    @classmethod
    def identity_oids(cls) -> list[str]:
        """Return list of identity OIDs."""
        return [cls.MODEL, cls.NAME, cls.FIRMWARE, cls.SERIAL]

    @classmethod
    def all_sensor_oids(cls) -> list[str]:
        """Return list of all sensor OIDs."""
        return [
            cls.BATTERY_CAPACITY,
            cls.BATTERY_TEMPERATURE,
            cls.BATTERY_RUNTIME,
            cls.BATTERY_VOLTAGE,
            cls.TIME_ON_BATTERY,
            cls.INPUT_VOLTAGE,
            cls.INPUT_FREQUENCY,
            cls.LAST_TRANSFER_CAUSE,
            cls.OUTPUT_STATUS,
            cls.OUTPUT_VOLTAGE_HIGH_PREC,
            cls.OUTPUT_FREQUENCY_HIGH_PREC,
            cls.OUTPUT_LOAD_HIGH_PREC,
            cls.OUTPUT_CURRENT_HIGH_PREC,
            cls.OUTPUT_EFFICIENCY_HIGH_PREC,
            cls.OUTPUT_ENERGY_HIGH_PREC,
            cls.OUTPUT_POWER,
        ]

    @classmethod
    def binary_sensor_oids(cls) -> list[str]:
        """Return list of binary sensor OIDs."""
        return [
            cls.BATTERY_STATUS,
            cls.BATTERY_REPLACE,
            cls.OUTPUT_STATUS,
        ]


# Battery status values
BATTERY_STATUS_UNKNOWN: Final = 1
BATTERY_STATUS_NORMAL: Final = 2
BATTERY_STATUS_LOW: Final = 3

BATTERY_STATUS_MAP: Final = {
    BATTERY_STATUS_UNKNOWN: "unknown",
    BATTERY_STATUS_NORMAL: "normal",
    BATTERY_STATUS_LOW: "low",
}

# Battery replace indicator values
BATTERY_REPLACE_NO: Final = 1
BATTERY_REPLACE_YES: Final = 2

# Output status values
OUTPUT_STATUS_UNKNOWN: Final = 1
OUTPUT_STATUS_ONLINE: Final = 2
OUTPUT_STATUS_ON_BATTERY: Final = 3
OUTPUT_STATUS_ON_SMART_BOOST: Final = 4
OUTPUT_STATUS_TIMED_SLEEPING: Final = 5
OUTPUT_STATUS_SOFTWARE_BYPASS: Final = 6
OUTPUT_STATUS_OFF: Final = 7
OUTPUT_STATUS_REBOOTING: Final = 8
OUTPUT_STATUS_SWITCHED_BYPASS: Final = 9
OUTPUT_STATUS_HARDWARE_FAILURE_BYPASS: Final = 10
OUTPUT_STATUS_SLEEPING_UNTIL_POWER_RETURN: Final = 11
OUTPUT_STATUS_ON_SMART_TRIM: Final = 12
OUTPUT_STATUS_ECO_MODE: Final = 13
OUTPUT_STATUS_HOT_STANDBY: Final = 14
OUTPUT_STATUS_ON_BATTERY_TEST: Final = 15

OUTPUT_STATUS_MAP: Final = {
    OUTPUT_STATUS_UNKNOWN: "unknown",
    OUTPUT_STATUS_ONLINE: "online",
    OUTPUT_STATUS_ON_BATTERY: "on_battery",
    OUTPUT_STATUS_ON_SMART_BOOST: "smart_boost",
    OUTPUT_STATUS_TIMED_SLEEPING: "timed_sleeping",
    OUTPUT_STATUS_SOFTWARE_BYPASS: "software_bypass",
    OUTPUT_STATUS_OFF: "off",
    OUTPUT_STATUS_REBOOTING: "rebooting",
    OUTPUT_STATUS_SWITCHED_BYPASS: "switched_bypass",
    OUTPUT_STATUS_HARDWARE_FAILURE_BYPASS: "hardware_failure_bypass",
    OUTPUT_STATUS_SLEEPING_UNTIL_POWER_RETURN: "sleeping_until_power_return",
    OUTPUT_STATUS_ON_SMART_TRIM: "smart_trim",
    OUTPUT_STATUS_ECO_MODE: "eco_mode",
    OUTPUT_STATUS_HOT_STANDBY: "hot_standby",
    OUTPUT_STATUS_ON_BATTERY_TEST: "battery_test",
}

# Self-test result values
SELF_TEST_OK: Final = 1
SELF_TEST_FAILED: Final = 2
SELF_TEST_INVALID: Final = 3
SELF_TEST_IN_PROGRESS: Final = 4

SELF_TEST_RESULT_MAP: Final = {
    SELF_TEST_OK: "ok",
    SELF_TEST_FAILED: "failed",
    SELF_TEST_INVALID: "invalid",
    SELF_TEST_IN_PROGRESS: "in_progress",
}

# Last transfer cause values
TRANSFER_NO_TRANSFER: Final = 1
TRANSFER_HIGH_LINE_VOLTAGE: Final = 2
TRANSFER_BROWNOUT: Final = 3
TRANSFER_BLACKOUT: Final = 4
TRANSFER_SMALL_SAG: Final = 5
TRANSFER_DEEP_SAG: Final = 6
TRANSFER_SMALL_SPIKE: Final = 7
TRANSFER_LARGE_SPIKE: Final = 8
TRANSFER_SELF_TEST: Final = 9
TRANSFER_RATE_OF_CHANGE: Final = 10

LAST_TRANSFER_CAUSE_MAP: Final = {
    TRANSFER_NO_TRANSFER: "No Transfer",
    TRANSFER_HIGH_LINE_VOLTAGE: "High Line Voltage",
    TRANSFER_BROWNOUT: "Brownout",
    TRANSFER_BLACKOUT: "Blackout",
    TRANSFER_SMALL_SAG: "Small Momentary Sag",
    TRANSFER_DEEP_SAG: "Deep Momentary Sag",
    TRANSFER_SMALL_SPIKE: "Small Momentary Spike",
    TRANSFER_LARGE_SPIKE: "Large Momentary Spike",
    TRANSFER_SELF_TEST: "Self Test",
    TRANSFER_RATE_OF_CHANGE: "Rate of Voltage Change",
}
