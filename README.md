# APC UPS and ATS SNMP for Home Assistant

Monitor APC Smart-UPS units and APC rack automatic transfer switches directly through their Network Management Card. No NUT server is required. The integration polls locally with SNMP v1, v2c, or v3. Each client reuses its SNMP engine and transport; after a connection failure or timeout, the next request resolves the hostname again. IPv4 and IPv6 literals are supported. Table discovery uses GETBULK for v2c/v3 and GETNEXT for v1 at setup, then hourly or when SNMP reports a cached row missing (at most once every five minutes). Temporary `-1` readings remain in the polling cache. Unsupported scalar OIDs are retried hourly. Normal polls read cached cells with GET requests of at most 20 bindings.

This integration is **read-only**. It does not send SNMP SET requests and provides no buttons, switches, outlet controls, shutdown commands, or calibration commands.

## Install

1. In HACS, open **Custom repositories**, add `https://github.com/davidcoulson/homeassistant-apc-ups`, and select **Integration**.
2. Download **APC UPS and ATS SNMP** and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → APC UPS and ATS (SNMP)**.
4. Enter the card's address, UDP port (normally 161), and SNMP version, then its credentials.

For manual installation, copy `custom_components/apc_ups_snmp` into your Home Assistant configuration's `custom_components` directory and restart. Home Assistant 2025.1 or newer is required.

Device type is detected automatically. All measurements supported by the card are registered; unsupported OIDs and APC's `-1` sentinel are skipped. Diagnostic measurements are generally disabled by default. Enable them on the device's entity page. Options contain the polling interval (10–300 seconds, default 30). Newly available measurements and table rows appear automatically without a reload. Use **Reconfigure** to change the address or credentials; forms retain current connection settings, community, username and protocols. Passwords are never prefilled; leave them blank during reconfiguration or reauthentication to keep stored passwords. Authentication failures offer a reauthentication flow.

Existing entity keys and unique IDs are retained. Legacy entries migrate to the UPS device type automatically. Previous sensor-picker selections no longer limit discovery; individual entity enable/disable settings remain in Home Assistant's entity registry. UPS status now uses NUT status words. Energy scaling is corrected to hundredths of a kWh; historical values recorded with the old scaling may need adjustment in Home Assistant statistics.

## Supported devices

- APC Smart-UPS and other UPS models implementing the PowerNet UPS subtree (`318.1.1.1`).
- APC rack ATS models implementing the PowerNet ATS subtree (`318.1.1.8`), including AP4452A and AP77xx-style output bank tables.
- NMC cards using v1, v2c, or v3. Actual coverage depends on the model and firmware.

AP4452A discovery and scaling are tested against a sanitized NMC2 walk; UPS coverage uses a synthetic Smart-UPS fixture. No live hardware is contacted by the tests. Hardware variants may expose only a subset of these entities.

## UPS entities

| Area | Measurements |
| --- | --- |
| Battery | Charge %, runtime (minutes), temperature, voltage, current, total current, nominal voltage, pack count, bad pack count, last replacement date, recommended replacement date, time on battery, restart charge threshold, low-runtime threshold |
| Input | Voltage, maximum/minimum voltage, frequency, transfer high/low thresholds, sensitivity, last transfer reason, line-failure count, phase count |
| Output | Voltage, frequency, current, load %, real power (W), apparent power (VA), efficiency, energy (kWh), nominal voltage/frequency, nominal VA and real-power ratings, phase count |
| Phase tables | Per-phase input voltage/current and voltage extrema; output voltage/current, apparent and real power/load and their extrema |
| Diagnostics | Manufacture date, self-test result/date, calibration result/date, startup/shutdown delays, ambient temperature/humidity when supported |
| Outlet groups | Named state sensor for each reported group |
| Status | Combined NUT words: OL, OB, LB, RB, BYPASS, OFF, TRIM, BOOST, OVER, CAL, ECO |
| Binary sensors | On battery, low battery, battery replacement needed, overload, on bypass, calibrating |

High-precision measurements take precedence over standard OIDs, with the appropriate scaling applied separately to each alternative. TimeTicks are hundredths of a second. Dates are preserved as reported by the card, including either slash or hyphen separators. Real power is reported only when measured; it is not estimated from an assumed power factor.

## ATS entities

| Area | Measurements |
| --- | --- |
| Sources | Selected and preferred source using configured input names (fallback Source A/B), nominal input voltage/frequency, sensitivity |
| Each input | Named voltage and frequency sensors, source fault binary sensors, diagnostic voltage orientation and input type; maximum/minimum voltage, current and apparent power where supported |
| Output phases | Voltage, current (0.1 A scaling), apparent power (VA), load %, diagnostic output frequency |
| Output banks | Current, voltage, real power and load state, where the bank table is supported |
| Status | Redundancy lost and overcurrent problem sensors; diagnostic communication, switch, source, output, hardware and power-supply fault sensors; front-panel lock and phase synchronization states |
| Identity | APC manufacturer, model, serial, firmware, name, manufacture date sensor, link to the card's web interface |

The AP4452A output phase power column reports **VA**, not watts. Unsupported output bank columns do not create entities. Input orientation and type are diagnostic metadata; named source fault binary sensors report health. Row names include phase or bank numbers only when multiple rows exist.

## Configure the card

Enable the chosen SNMP protocol in the NMC web interface and create a read-only community or v3 user. Configure the NMC's **SNMP access-control list with Home Assistant's source IP**; enabling SNMP alone is insufficient. Permit UDP 161 through intervening firewalls. A rejected community or access list may appear as a timeout, especially with v1/v2c.

SNMP v1 and v2c send community strings and data in cleartext. Use them only on trusted networks. Prefer SNMP v3 with authentication and privacy where supported. The v3 form supports MD5/SHA-family authentication and DES/3DES/AES-family privacy, subject to the card's support. Select protocols explicitly: authentication requires both a protocol and password; privacy requires authentication and both a privacy protocol and password. All passwords must contain at least eight characters. MD5 and DES are never selected implicitly. pysnmp is pinned to 7.1.29: 7.1.30 imports cipher APIs unavailable in the cryptography version pinned by the tested Home Assistant release.

Diagnostic downloads contain raw OID values with connection credentials, host, device names and serials redacted. Review remaining device information before sharing.

## Development

```sh
uv venv --python 3.13 .venv
uv pip install --python .venv -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/ruff check .
```

Tests use fixture-backed responses, mocked transport calls, and real pysnmp responders bound only to ephemeral ports on `127.0.0.1`. Both walk fixtures are exercised over v1, v2c and v3 SHA/AES, including missing OIDs, bulk termination, authentication failures and timeouts. Reference driver source is not included. OIDs, enum definitions and scaling are derived from the APC PowerNet MIB and NUT mappings; no GPL driver code is copied.

Fork maintained by David Coulson. Based on [Sean Greenhalgh's original integration](https://github.com/scgreenhalgh/homeassistant-apc-ups). Distributed under the original MIT [license](LICENSE).

## Branding

The APC logo in `custom_components/apc_ups_snmp/brand/` is a trademark of Schneider Electric. It is the same image
Home Assistant uses for its built-in APC UPS Daemon integration (from the
[home-assistant/brands](https://github.com/home-assistant/brands) repository), and is used only to identify the
devices this integration works with. This project is not affiliated with or endorsed by Schneider Electric.
