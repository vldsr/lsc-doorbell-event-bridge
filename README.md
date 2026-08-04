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

# Official references

- LSC Tuya Doorbell v2 — Home Assistant Integration: <https://github.com/jurgenmahn/ha_tuya_doorbell>
- Home Assistant Tuya integration: <https://www.home-assistant.io/integrations/tuya/>
- Tuya Smart Home project configuration: <https://developer.tuya.com/en/docs/iot/Platform_Configuration_smarthome?id=Kamcgamwoevrx>
- Tuya Smart Home quick start: <https://developer.tuya.com/en/docs/iot/smart-home-quick-start?id=Kbvwrxn6mngbd>
- Tuya Message Service: <https://developer.tuya.com/en/docs/iot/manage-messages?id=Ka49p7loog3ze>
- Home Assistant App repositories: <https://developers.home-assistant.io/docs/apps/repository/>
- Home Assistant local App testing: <https://developers.home-assistant.io/docs/apps/testing/>
