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

    The IPC movement-configs API returns a temporary signed URL for a resource.
    The downloaded object is a Tuya container, not a raw JPEG. Its payload is
    AES-CBC encrypted with the media resource key supplied in the event.
    """

    _DIRECT_STORAGE_HOSTS = {
        "china": "https://ty-cn-storage30.s3.cn-north-1.amazonaws.com.cn",
        "america": "https://ty-us-storage30.s3.us-east-1.amazonaws.com",
        "central_europe": "https://ty-eu-storage30.s3.eu-central-1.amazonaws.com",
        "india": "https://ty-in-storage30.s3.ap-south-1.amazonaws.com",
    }

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

        The direct storage URL is only used when the Cloud API call fails.
        """
        bucket = str(media.get("bucket") or "").strip()
        path = str(media.get("path") or "").strip()
        resource_id = str(media.get("resource_id") or "").strip()
        if not bucket or not path or not resource_id:
            raise TuyaCloudError(f"Incomplete media reference: {media!r}")

        errors: list[str] = []
        try:
            url = self._get_biz_url(device_id, bucket, path)
            LOGGER.debug("Tuya Cloud returned media URL for %s", device_id)
            container = self._download(url)
            return self._decrypt_container(container, resource_id)
        except Exception as error:
            errors.append(f"Cloud API: {error}")
            LOGGER.debug("Tuya Cloud media URL failed: %s", error)

        try:
            url = self._direct_storage_url(bucket, path)
            LOGGER.debug("Trying direct Tuya storage URL: %s", url)
            container = self._download(url)
            return self._decrypt_container(container, resource_id)
        except Exception as error:
            errors.append(f"direct storage: {error}")
            raise TuyaCloudError("; ".join(errors)) from error

    def _get_biz_url(self, device_id: str, bucket: str, path: str) -> str:
        query = f"?bucket={quote(bucket, safe='')}&file_path={quote(path, safe='/')}"
        body = self._request("GET", f"/v1.0/devices/{quote(device_id, safe='')}/movement-configs{query}")
        if not body.get("success"):
            raise TuyaCloudError(str(body.get("msg") or body))
        result = body.get("result")
        if isinstance(result, str) and result:
            return result
        if isinstance(result, dict):
            for key in ("bizUrl", "url", "fileUrl"):
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

    def _direct_storage_url(self, bucket: str, path: str) -> str:
        # Tuya event buckets are normally named like ty-eu-storage30-pic.
        # Convert the bucket name to the corresponding S3 host.
        bucket_name = bucket.replace("-pic", "")
        if bucket_name.startswith("ty-eu-"):
            host = "https://ty-eu-storage30.s3.eu-central-1.amazonaws.com"
        elif bucket_name.startswith("ty-us-"):
            host = "https://ty-us-storage30.s3.us-east-1.amazonaws.com"
        elif bucket_name.startswith("ty-cn-"):
            host = "https://ty-cn-storage30.s3.cn-north-1.amazonaws.com.cn"
        elif bucket_name.startswith("ty-in-"):
            host = "https://ty-in-storage30.s3.ap-south-1.amazonaws.com"
        else:
            raise TuyaCloudError(f"Unsupported Tuya storage bucket: {bucket}")
        return host + "/" + path.lstrip("/")

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
