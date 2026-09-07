# LSC Doorbell Event Bridge

A Home Assistant App for selected battery-powered LSC/Tuya video doorbells.

It receives events through the Tuya Message Service and exposes a dedicated MQTT device in Home Assistant, including motion detection, doorbell presses, snapshots, power mode, and battery level.

This project is primarily intended for battery-powered devices that cannot maintain a stable local connection.

For wired doorbells or devices that can be accessed reliably over the local network, consider [LSC Tuya Doorbell v2 — Home Assistant Integration](https://github.com/jurgenmahn/ha_tuya_doorbell).

## Features

- Complete multilingual Web UI in English, Italian, German, French, and Spanish.
- Independent snapshot controls for doorbell presses, motion events, and periodic captures.
- Configurable snapshot interval, delay, and retention.
- Persistent photo archive with multi-select download and deletion.
- Camera and Device ID suggestions from Home Assistant, where available.
- No YAML editing required for normal configuration.
- Snapshots are stored in Home Assistant's `/media/lsc_doorbell/snapshots` directory.
- Snapshots are automatically available through Home Assistant's built-in Media Source.
- The snapshot API also returns a ready-to-use `media-source://` URI.

## Media Source

The App stores the snapshot archive in Home Assistant's `/media` directory. Home Assistant's built-in Media Source automatically exposes this directory in **Media > My media**, so no custom Media Source integration or additional YAML configuration is required.

The archive root is:

```text
media-source://media_source/local/lsc_doorbell/snapshots
```

Snapshots are grouped by doorbell/device. The `/api/snapshots` response includes a `media_source` field for every snapshot with its corresponding URI.

When upgrading from an older version that stored snapshots under `/media/lsc_doorbell/snapshots`, the App automatically migrates existing JPEG files to `/media/lsc_doorbell/snapshots`.

## Installation

Add this repository to the Home Assistant App Store:

```text
https://github.com/GiannBart/lsc-doorbell-event-bridge
```

Then install **LSC Doorbell Event Bridge** and open its Web UI.

For the complete illustrated setup procedure, see the [installation guide](docs/INSTALLATION.md).

## Acknowledgements and related projects

This project originally started while experimenting with [LSC Tuya Doorbell v2 — Home Assistant Integration](https://github.com/jurgenmahn/ha_tuya_doorbell), created by [Jürgen Mahn](https://github.com/jurgenmahn).

Although LSC Doorbell Event Bridge later evolved into an independent project with a substantially different architecture and implementation, Jürgen's work was an important starting point and source of inspiration.

The two projects address different use cases:

- **LSC Doorbell Event Bridge** receives cloud events through the Tuya Message Service and publishes them through MQTT. It is primarily intended for battery-powered devices.
- **LSC Tuya Doorbell v2** communicates locally with compatible devices and is particularly suitable for wired or reliably accessible doorbells.

Many thanks to Jürgen for his work and for sharing it with the Home Assistant community.

## Official documentation

- [Home Assistant Tuya integration](https://www.home-assistant.io/integrations/tuya/)
- [Tuya Smart Home project configuration](https://developer.tuya.com/en/docs/iot/Platform_Configuration_smarthome?id=Kamcgamwoevrx)
- [Tuya Smart Home quick start](https://developer.tuya.com/en/docs/iot/smart-home-quick-start?id=Kbvwrxn6mngbd)
- [Tuya Message Service](https://developer.tuya.com/en/docs/iot/manage-messages?id=Ka49p7loog3ze)
- [Home Assistant App repositories](https://developers.home-assistant.io/docs/apps/repository/)
- [Home Assistant local App testing](https://developers.home-assistant.io/docs/apps/testing/)
