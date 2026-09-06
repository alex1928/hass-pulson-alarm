# PulsON Alarm — Home Assistant integration

[![hacs][hacs-badge]][hacs]

Home Assistant custom integration for **PulsON Alarm** panels (PulsON Alarm 2.0 4G / PAV204G / CP80,
made by BCS Sp. z o.o.). Talks to the vendor cloud over MQTT — the same channel the official mobile
app uses — so no extra hardware is required.

> There is no official Home Assistant support for these panels. The protocol here was
> reverse-engineered for interoperability with hardware the author owns
> (permitted under art. 75(2)(3) of the Polish Copyright Act / EU Directive 2009/24/EC).
> Not affiliated with or endorsed by BCS / PulsON.

## Features

| Entity | What it gives you |
|---|---|
| `alarm_control_panel` (per partition) | live state, arm away / arm night / disarm (disarm requires the PIN) |
| `binary_sensor` (per zone) | open / closed, with name from the panel |
| `binary_sensor` (per zone, *enabled by default*) | tamper / fault |
| `binary_sensor` (per partition) | alarm active |
| `binary_sensor` | IP/Wi-Fi module online, GSM module online |
| `binary_sensor` | installer programming (service) mode |
| `switch` (per output) | PGM output on/off |
| `switch` (per zone) | bypass / un-bypass |

Push-based — the panel reports changes, no polling.

## Installation

### HACS (recommended)

1. Open **HACS**, click the ⋮ menu in the top right corner and choose **Custom repositories**
2. Add `https://github.com/alex1928/hass-pulson-alarm`, set **Type** to **Integration**, click **ADD**
3. Search for **PulsON Alarm**, click **Download**, then restart Home Assistant

### Manual

Copy `custom_components/pulson_alarm/` into your Home Assistant `config/custom_components/`
directory and restart.

## Configuration

**Settings → Devices & Services → Add Integration → PulsON Alarm.**

Paste the panel's QR payload. Read it from the keypad: **Menu → QR code → System**. It looks like:

```
1;solid.pulsonalarm.pl;8883;1234;0011223344556677889900aa
  └─ host          └─ port └─ PIN └─ System ID
```

That single string carries everything. Alternatively use the manual step and enter host,
System ID and PIN separately.

> **The host is per-panel.** PulsON assigns panels to different cloud shards
> (`solid.`, `nss.`, `serwer.pulsonalarm.pl`). Always take it from your own QR code.

## How it works

- MQTT **3.1** over TLS to `HOST:8883` (the broker rejects 3.1.1 / 5).
- Credentials are derived from System ID + PIN with fixed salts.
- Reading state is two-step: subscribe to the retained index lists, then subscribe to the
  **exact per-element leaf topics** — the panel only publishes a value once its specific leaf is
  subscribed (a `#` wildcard is not enough).
- Commands publish to `system/{sid}/{module}/{id}/{action}` with payload `{PIN}/{value}`.

Full protocol write-up (in Polish): [`docs/pulson-ha-integration-spec.md`](docs/pulson-ha-integration-spec.md).

## Standalone CLI

[`tools/pulson.py`](tools/pulson.py) is a dependency-free reference client (stdlib only) — useful for
testing without Home Assistant:

```bash
export PULSON_HOST=solid.pulsonalarm.pl
export PULSON_SID=0011223344556677889900aa
export PULSON_PIN=xxxx
python3 tools/pulson.py status
python3 tools/pulson.py watch
python3 tools/pulson.py arm 1
```

## Limitations

- **Cloud-dependent.** If the vendor cloud is down, control and state are unavailable.
  For critical automations consider also wiring panel PGM outputs to an ESPHome/Shelly input.
- **Panel configuration is not editable** (zones, timers, outputs, EN‑50131 options, users).
  The mobile app can't do it either — that needs the Windows *AlarmConfiguration* software.
- The mobile app's "Settings" screen is app-local (name, biometrics, push-notification filter)
  and is intentionally not mirrored here.
- Event push notifications go through Firebase (FCM) in the vendor app; this integration reads
  live state from MQTT instead and does not use FCM.
- Verified against `solid.pulsonalarm.pl`. Other PulsON cloud hosts are expected to work — the
  protocol is host-agnostic — but are untested.

## Security

Your **System ID + PIN grant full remote control of the alarm.** Never commit them, paste them
into issues, or share the QR code.

- The PIN is stored in Home Assistant's `.storage` directory **in plain text**, and it is included
  in whatever Home Assistant backups you take. Protect your backups accordingly.
- Disarming a partition through this integration requires that same PIN; arming does not.
- This integration **does not replace the keypad or the connection to your monitoring station**.
  It is an additional remote-control channel alongside them, not a substitute for either.
- Installing and using this integration may affect your alarm's **warranty, your insurance
  policy, or your monitoring contract.** Check your terms before relying on it, and tell your
  monitoring station before testing arm/disarm through it on a live, supervised installation.
- Panic/hold-up is deliberately **not** exposed as an entity — it raises a real hold-up alarm at the
  monitoring station.

## License

MIT — see [LICENSE](LICENSE).

[hacs]: https://github.com/hacs/integration
[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
