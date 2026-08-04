# LSC Doorbell Event Bridge

Home Assistant App for selected LSC/Tuya-Battery powered video doorbells. It receives Tuya Message Service events and exposes a focused MQTT device with Motion, Pressed, Snapshot, Power mode and Battery.
For a local setup and for wired doorbells, I suggest jurgenmahn's repository: https://github.com/jurgenmahn/ha_tuya_doorbell

## Features

- Complete multilingual Web UI: English, Italian, German, French and Spanish.
- Independent snapshot toggles for press, motion and periodic capture.
- Configurable snapshot interval, delay and retention.
- Persistent photo archive with multi-select download and deletion.
- Camera and Device ID suggestions from Home Assistant where available.
- No YAML editing required for normal configuration.

## Installation

Add this repository to the Home Assistant App store:

```text
https://github.com/GiannBart/lsc-doorbell-event-bridge
```

Then install **LSC Doorbell Event Bridge** and open its Web UI.

Read the illustrated, end-to-end setup guide: **[Complete installation guide](docs/INSTALLATION.md)**.

## Repository contents

- `repository.yaml` — Home Assistant repository metadata.
- `lsc_doorbell_bridge/` — the App.
- `docs/` — installation guide and sanitized documentation images.
- `LICENSE` — license terms.

No test suites, test reports, caches or development-only files are included in the release repository.

## Security

Never publish Access Secret, Device ID, subscription names, account QR codes, UUIDs or private snapshot paths.
