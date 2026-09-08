# Changelog

## 1.2.2

- Download Tuya IPC snapshots from the `movement-configs` URL resolver when an event contains media metadata.
- Publish Tuya cloud snapshots through the existing MQTT snapshot pipeline.
- Do not fall back to a Home Assistant camera snapshot when a Tuya cloud download fails.
- Add explicit logging for encrypted download and decrypted JPEG sizes.
- Include `tuya_client.py` in the Docker image to fix `ModuleNotFoundError: No module named 'tuya_client'`.

## 1.2.1
- Keep Tuya Pulsar media resolution on the documented `movement-configs` API.
- Remove the invalid unsigned S3 fallback (private Tuya storage returns 403).
- Improve diagnostics for an unsubscribed `movement-configs` API.
- Document that Smart Life `m.ipc.storage.event.timerange.query` / `thing.m.ipc.storage.secret.get` are Smart App SDK session APIs, not direct replacements for project OpenAPI credentials.

# Changelog

## 1.1.1

- Store snapshot archive in Home Assistant `/media/lsc_doorbell/snapshots`.
- Expose snapshots automatically through Home Assistant built-in Media Source.
- Migrate existing snapshots from `/media/lsc_doorbell/snapshots` on first start after upgrade.
- Add `media_source` URI to `/api/snapshots` response.


## 1.0.0

- All normal configuration moved to the Ingress Web UI.
- Added independent toggles for snapshots on press, motion and periodic timer.
- Added configurable periodic interval.
- Added configurable photo retention from 2 to 3650 days.
- Removed the five-photo limit; all photos are retained until expiration or manual deletion.
- Added multi-select archive management.
- Added download of one or more selected photos as a ZIP archive.
- Added deletion of one or more selected photos.
- Kept the focused entity set: Motion, Pressed, Snapshot, Power mode and Battery.
