# LSC Doorbell Event Bridge

See [DOCS.md](DOCS.md) for App documentation and the repository [installation guide](../docs/INSTALLATION.md).


### Tuya media resolution

For Pulsar `alarm_message` media, the bridge resolves the `bucket/path` reference through Tuya `movement-configs`, then downloads and AES-CBC decrypts the returned private object. A bare S3 bucket/object URL is intentionally not used because Tuya storage objects are private. Tuya support documents `movement_detect_pic` as requiring this URL-resolution API and notes that the API may require subscription.
