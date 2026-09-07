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
