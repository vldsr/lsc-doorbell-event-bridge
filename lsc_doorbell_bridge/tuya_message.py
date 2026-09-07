"""Tuya Message Service authentication, decryption, and payload parsing."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable



@dataclass(frozen=True)
class ParsedEvent:
    """Normalized Tuya event."""

    kind: str
    source: str
    timestamp: int | None = None
    command: str | None = None
    media: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


def build_authentication(pulsar_module: Any, access_id: str, access_secret: str) -> Any:
    """Build Tuya's Pulsar auth1 credentials."""
    secret_md5 = hashlib.md5(access_secret.encode("utf-8")).hexdigest()  # noqa: S324
    combined_md5 = hashlib.md5((access_id + secret_md5).encode("utf-8")).hexdigest()  # noqa: S324
    password = '"' + combined_md5[8:24] + '"}'
    username = '{{"username": "{}","password"'.format(access_id)
    return pulsar_module.AuthenticationBasic(username, password, "auth1")


def decrypt_envelope(payload: bytes | str, encryption_mode: str | None, access_secret: str) -> dict[str, Any]:
    """Decrypt one Tuya Pulsar envelope and return the inner JSON object."""
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad

    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    envelope = json.loads(payload)
    encrypted = base64.b64decode(envelope["data"])
    key = access_secret[8:24].encode("utf-8")
    if len(key) != 16:
        raise ValueError("The Access Secret must contain at least 24 characters")

    if encryption_mode == "aes_gcm":
        if len(encrypted) < 28:
            raise ValueError("AES-GCM payload is too short")
        nonce, ciphertext, tag = encrypted[:12], encrypted[12:-16], encrypted[-16:]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
    else:
        cipher = AES.new(key, AES.MODE_ECB)
        padded = cipher.decrypt(encrypted)
        try:
            plaintext = unpad(padded, AES.block_size)
        except ValueError:
            plaintext = padded.rstrip(b"\x00")

    return json.loads(plaintext.decode("utf-8").strip())


def decode_embedded_message(value: Any) -> dict[str, Any] | None:
    """Decode the Base64 JSON stored in initiative_message / DP 212."""
    if not isinstance(value, str) or not value:
        return None
    try:
        padded = value + ("=" * (-len(value) % 4))
        decoded = base64.b64decode(padded).decode("utf-8")
        result = json.loads(decoded)
        return result if isinstance(result, dict) else None
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def normalize_media(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize the first Tuya media resource reference."""
    files = payload.get("files")
    if not isinstance(files, list) or not files or not isinstance(files[0], list):
        return None
    item = files[0]
    media = {
        "bucket": item[0] if len(item) > 0 else None,
        "path": item[1] if len(item) > 1 else None,
        "resource_id": item[2] if len(item) > 2 else None,
        "expires_at": item[3] if len(item) > 3 else None,
        "type": payload.get("type"),
        "with": payload.get("with"),
    }
    return {key: value for key, value in media.items() if value is not None}


def _csv_set(value: str | Iterable[str]) -> set[str]:
    if isinstance(value, str):
        values = value.split(",")
    else:
        values = value
    return {str(item).strip().lower() for item in values if str(item).strip()}


def parse_message(
    message: dict[str, Any],
    doorbell_commands: str | Iterable[str],
    motion_commands: str | Iterable[str],
) -> list[ParsedEvent]:
    """Convert a decrypted Tuya message to normalized state/events."""
    events: list[ParsedEvent] = []
    doorbell = _csv_set(doorbell_commands)
    motion = _csv_set(motion_commands)

    status = message.get("status")
    if isinstance(status, list):
        for item in status:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "")).lower()
            value = item.get("value")
            timestamp = item.get("t")

            if code == "wireless_electricity":
                events.append(ParsedEvent("battery", code, timestamp, raw={"value": value}))
            elif code == "wireless_powermode":
                events.append(ParsedEvent("power_mode", code, timestamp, raw={"value": value}))
            elif code == "wireless_awake":
                if isinstance(value, str):
                    awake = value.strip().lower() in {"1", "true", "on", "yes"}
                else:
                    awake = bool(value)
                events.append(ParsedEvent("awake", code, timestamp, raw={"value": awake}))
            elif code == "initiative_message" or "alarm_message" or "212" in item:
                message_value = item.get("185") if "185" in item else value if value is not None else item.get("212")
                embedded = decode_embedded_message(message_value)
                if not embedded:
                    continue
                command = str(embedded.get("cmd", "")).lower()
                media = normalize_media(embedded)
                event_timestamp = embedded.get("time") or timestamp
                if command in doorbell:
                    events.append(ParsedEvent("doorbell", "initiative_message", event_timestamp, command, media, embedded))
                elif command in motion:
                    events.append(ParsedEvent("motion", "initiative_message", event_timestamp, command, media, embedded))
                else:
                    events.append(ParsedEvent("unknown_command", "initiative_message", event_timestamp, command, media, embedded))

    if str(message.get("bizCode", "")).lower() == "event_notify":
        biz_data = message.get("bizData")
        if isinstance(biz_data, dict):
            event_type = str(biz_data.get("etype", "")).lower()
            if event_type == "ac_doorbell":
                events.append(ParsedEvent("doorbell", "event_notify", message.get("ts"), event_type, None, biz_data))

    return events
