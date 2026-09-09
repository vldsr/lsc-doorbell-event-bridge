"""Tuya Cloud media client for IPC/doorbell snapshots."""

from __future__ import annotations

import hashlib
import hmac
import logging
import struct
import time
from typing import Any
from urllib.parse import quote

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

LOGGER = logging.getLogger("lsc_doorbell_bridge.tuya_client")


class TuyaCloudError(RuntimeError):
    """Raised when Tuya Cloud cannot return a media file."""


class TuyaCloudClient:
    """Download and decrypt IPC media referenced by Tuya event messages.

    For Pulsar ``alarm_message`` resources Tuya documents the
    ``movement-configs`` API as the URL-resolution API.  The Smart Life APK
    also contains the internal CloudBusiness APIs
    ``m.ipc.storage.event.timerange.query`` and
    ``thing.m.ipc.storage.secret.get``; those belong to the Smart App SDK
    session and are not interchangeable with the project OpenAPI credentials
    used by this bridge.

    The object returned by ``movement-configs`` is a Tuya encrypted container,
    not a raw JPEG. Its payload is AES-CBC encrypted with the resource key
    supplied in the Pulsar media reference.
    """

    def __init__(self, access_id: str, access_secret: str, endpoint: str, timeout: float = 20) -> None:
        self.access_id = access_id
        self.access_secret = access_secret
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._session = requests.Session()

    def close(self) -> None:
        self._session.close()

    def download_media(self, device_id: str, media: dict[str, Any]) -> bytes:
        """Get the media URL through Cloud API, then download/decrypt the file.

        Direct object-storage access is intentionally not attempted: Tuya media
        objects are private and require a URL resolved by Tuya Cloud.
        """
        bucket = str(media.get("bucket") or "").strip()
        path = str(media.get("path") or "").strip()
        resource_id = str(media.get("resource_id") or "").strip()
        if not bucket or not path or not resource_id:
            raise TuyaCloudError(f"Incomplete media reference: {media!r}")

        errors: list[str] = []
        for attempt in range(3):
            try:
                url = self._get_biz_url(device_id, bucket, path)
                LOGGER.debug("Tuya Cloud returned media URL for %s", device_id)
                container = self._download(url)
                LOGGER.info("Downloaded %d bytes of encrypted Tuya media for %s", len(container), device_id)
                jpeg = self._decrypt_container(container, resource_id)
                LOGGER.info("Decrypted Tuya media to %d-byte JPEG for %s", len(jpeg), device_id)
                return jpeg
            except Exception as error:
                errors.append(f"movement-configs: {error}")
                LOGGER.debug("Tuya Cloud media URL failed: %s", error)
                LOGGER.warning("Attempt %d/3 failed for Tuya media %s: %s",attempt + 1,device_id,error)
            if attempt < 2:
                time.sleep(1)
        # Do not try to construct an S3 URL here. Tuya storage objects are
        # private and a bare bucket/object URL normally returns HTTP 403.
        # A signed URL must be returned by a Tuya API.
        raise TuyaCloudError(
            "; ".join(errors)
            + "; direct S3 access is not supported because the Tuya storage object is private"
        )

    def _get_biz_url(self, device_id: str, bucket: str, path: str) -> str:
        """Resolve a Pulsar bucket/path to a temporary signed URL.

        Tuya's support documentation explicitly points to this API for
        ``movement_detect_pic`` resources and notes that a subscription may be
        required.  The response can be either a string or an object containing
        a URL field, depending on the API version.
        """
        query = f"?bucket={quote(bucket, safe='')}&file_path={quote(path, safe='/')}"
        api_path = (
            f"/v1.0/devices/{quote(device_id, safe='')}"
            f"/movement-configs{query}"
        )
        body = self._request("GET", api_path)
        if not body.get("success"):
            message = str(body.get("msg") or body)
            if "not subscribed" in message.lower() or "no permissions" in message.lower():
                raise TuyaCloudError(
                    "Tuya movement-configs API is not subscribed for this project. "
                    "Tuya documents this API as the URL resolver for movement_detect_pic; "
                    "request the API subscription in Tuya IoT Platform/support. "
                    f"Response: {message}"
                )
            raise TuyaCloudError(message)
        result = body.get("result")
        if isinstance(result, str) and result:
            return result
        if isinstance(result, dict):
            for key in ("bizUrl", "url", "fileUrl", "snapshotUrl"):
                value = result.get(key)
                if isinstance(value, str) and value:
                    return value
        raise TuyaCloudError(f"No media URL in response: {body!r}")

    def _request(self, method: str, path: str, body: bytes = b"") -> dict[str, Any]:
        token = self._ensure_token()
        timestamp = str(int(time.time() * 1000))
        content_hash = hashlib.sha256(body).hexdigest()
        string_to_sign = f"{method}\n{content_hash}\n\n{path}"
        sign = self._sign(self.access_id + token + timestamp + string_to_sign)
        response = self._session.request(
            method,
            self.endpoint + path,
            headers={
                "client_id": self.access_id,
                "access_token": token,
                "sign": sign,
                "sign_method": "HMAC-SHA256",
                "t": timestamp,
                "Content-Type": "application/json",
            },
            data=body or None,
            timeout=self.timeout,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise TuyaCloudError(f"Unexpected Tuya response: {result!r}")
        return result

    def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token

        timestamp = str(int(time.time() * 1000))
        token_path = "/v1.0/token?grant_type=1"
        content_hash = hashlib.sha256(b"").hexdigest()
        string_to_sign = f"GET\n{content_hash}\n\n{token_path}"
        sign = self._sign(self.access_id + timestamp + string_to_sign)
        response = self._session.get(
            self.endpoint + token_path,
            headers={
                "client_id": self.access_id,
                "sign": sign,
                "sign_method": "HMAC-SHA256",
                "t": timestamp,
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("success"):
            raise TuyaCloudError(str(body.get("msg") or body))
        result = body.get("result") or {}
        token = result.get("access_token")
        if not token:
            raise TuyaCloudError(f"No access token in response: {body!r}")
        self._token = str(token)
        self._token_expires_at = time.time() + int(result.get("expire_time", 7200))
        return self._token

    def _sign(self, message: str) -> str:
        return hmac.new(
            self.access_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()

    def _download(self, url: str) -> bytes:
        response = self._session.get(url, timeout=self.timeout)
        response.raise_for_status()
        if not response.content:
            raise TuyaCloudError("Tuya storage returned an empty response")
        return response.content

    @staticmethod
    def _decrypt_container(container: bytes, resource_id: str) -> bytes:
        # Tuya IPC media object format observed for movement images:
        #   int32 version + 16-byte IV + 44-byte metadata + AES-CBC payload.
        if len(container) <= 64:
            raise TuyaCloudError("Tuya media object is too small")

        _version = struct.unpack("i", container[:4])[0]
        iv = container[4:20]
        encrypted = container[64:]
        if not encrypted or len(encrypted) % AES.block_size:
            raise TuyaCloudError("Invalid encrypted Tuya media payload")

        key = resource_id.encode("utf-8")
        if len(key) not in (16, 24, 32):
            raise TuyaCloudError(
                f"Unsupported Tuya media key length: {len(key)} bytes"
            )

        cipher = AES.new(key, AES.MODE_CBC, iv)
        try:
            plain = unpad(cipher.decrypt(encrypted), AES.block_size)
        except ValueError as error:
            raise TuyaCloudError("Unable to decrypt Tuya media payload") from error

        if not plain.startswith(b"\xff\xd8"):
            raise TuyaCloudError("Decrypted Tuya media is not a JPEG")
        return plain
