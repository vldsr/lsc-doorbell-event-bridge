"""Home Assistant camera helpers used by the App and its setup UI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

SUPERVISOR_CORE_API = "http://supervisor/core/api"
HOME_ASSISTANT_INTERNAL = "http://homeassistant:8123"


class CameraError(RuntimeError):
    """Raised when a Home Assistant camera cannot be queried or captured."""


@dataclass(frozen=True)
class CameraUrls:
    """URLs derived from a Home Assistant camera entity."""

    image_url: str | None
    stream_url: str
    entity_picture: str | None


class HomeAssistantCameraClient:
    """Read camera entities and retrieve snapshots through the Core API proxy."""

    def __init__(
        self,
        *,
        timeout: float = 20,
        session: requests.Session | None = None,
    ) -> None:
        token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
        if not token:
            raise CameraError("SUPERVISOR_TOKEN is not available")
        self.timeout = float(timeout)
        self.session = session or requests.Session()
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _get_json(self, path: str) -> Any:
        response = self.session.get(
            f"{SUPERVISOR_CORE_API}{path}",
            headers=self.headers,
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            detail = response.text.strip()[:500]
            raise CameraError(f"Home Assistant API request failed for {path}: {detail}") from error

    def list_cameras(self) -> list[dict[str, Any]]:
        """Return camera entities available in Home Assistant."""
        states = self._get_json("/states")
        if not isinstance(states, list):
            raise CameraError("Home Assistant returned an invalid states response")

        cameras: list[dict[str, Any]] = []
        for state in states:
            if not isinstance(state, dict):
                continue
            entity_id = str(state.get("entity_id", ""))
            if not entity_id.startswith("camera."):
                continue
            attributes = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
            candidates: list[str] = []
            for key in ("device_id", "dev_id", "devId", "uuid"):
                value = attributes.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())
            cameras.append(
                {
                    "entity_id": entity_id,
                    "name": str(attributes.get("friendly_name") or entity_id),
                    "state": str(state.get("state", "unknown")),
                    "entity_picture": attributes.get("entity_picture"),
                    "device_id_candidates": candidates,
                }
            )
        cameras.sort(key=lambda item: (item["name"].casefold(), item["entity_id"]))
        return cameras

    def get_state(self, entity_id: str) -> dict[str, Any]:
        entity_id = entity_id.strip()
        if not entity_id.startswith("camera."):
            raise CameraError(f"Invalid camera entity: {entity_id!r}")
        state = self._get_json(f"/states/{entity_id}")
        if not isinstance(state, dict):
            raise CameraError(f"Invalid state response for {entity_id}")
        return state

    @staticmethod
    def _absolute_url(value: str | None) -> str | None:
        if not value:
            return None
        if value.startswith("http://") or value.startswith("https://"):
            return value
        if value.startswith("/"):
            return f"{HOME_ASSISTANT_INTERNAL}{value}"
        return f"{HOME_ASSISTANT_INTERNAL}/{value}"

    def urls(self, entity_id: str) -> CameraUrls:
        """Build the still-image and stream URLs for a selected camera."""
        state = self.get_state(entity_id)
        attributes = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
        picture = attributes.get("entity_picture")
        picture = str(picture) if picture else None

        token = attributes.get("access_token")
        if not token and picture:
            try:
                token = parse_qs(urlparse(picture).query).get("token", [None])[0]
            except (TypeError, ValueError):
                token = None

        # Keep the user-visible stream URL relative and token-free. Home Assistant
        # resolves it with the logged-in user's session when opened in the frontend.
        stream_path = f"/api/camera_proxy_stream/{entity_id}"

        return CameraUrls(
            image_url=self._absolute_url(picture),
            stream_url=stream_path,
            entity_picture=picture,
        )

    def capture(self, entity_id: str) -> bytes:
        """Return a JPEG snapshot from the selected Home Assistant camera."""
        entity_id = entity_id.strip()
        if not entity_id.startswith("camera."):
            raise CameraError(f"Invalid camera entity: {entity_id!r}")

        response = self.session.get(
            f"{SUPERVISOR_CORE_API}/camera_proxy/{entity_id}",
            headers={
                "Authorization": self.headers["Authorization"],
                "Accept": "image/jpeg,image/*;q=0.9",
            },
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except requests.RequestException as error:
            detail = response.text.strip()[:500]
            raise CameraError(
                f"Camera proxy failed for {entity_id}: {error}; response={detail!r}"
            ) from error

        payload = response.content
        if not payload.startswith(b"\xff\xd8\xff"):
            content_type = response.headers.get("Content-Type", "unknown")
            raise CameraError(
                f"Camera proxy for {entity_id} did not return a JPEG "
                f"({len(payload)} bytes, content type {content_type})"
            )
        return payload
