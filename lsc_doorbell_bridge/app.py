"""LSC Doorbell Event Bridge Home Assistant App."""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import pulsar
import requests

from config_ui import ConfigurationService
from ha_camera import CameraError, HomeAssistantCameraClient
from storage import SNAPSHOT_ROOT
from tuya_message import (
    ParsedEvent,
    build_authentication,
    decrypt_envelope,
    parse_message,
)

OPTIONS_PATH = Path("/data/options.json")
SUPERVISOR_URL = "http://supervisor"
PULSAR_ENDPOINTS = {
    "china": "pulsar+ssl://mqe.tuyacn.com:7285/",
    "america": "pulsar+ssl://mqe.tuyaus.com:7285/",
    "central_europe": "pulsar+ssl://mqe.tuyaeu.com:7285/",
    "india": "pulsar+ssl://mqe.tuyain.com:7285/",
}
DOORBELL_COMMANDS = "ipc_doorbell"
MOTION_COMMANDS = "ipc_motion,ipc_human,ipc_passby"
DISCOVERY_PREFIX = "homeassistant"
TOPIC_PREFIX = "lsc_doorbell"

LOGGER = logging.getLogger("lsc_doorbell_bridge")
STOP = threading.Event()


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def slugify(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_").lower()
    return result or "doorbell"


def supervisor_get(path: str) -> dict[str, Any]:
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    response = requests.get(
        f"{SUPERVISOR_URL}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    response.raise_for_status()
    body = response.json()
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) else body


class MqttPublisher:
    """Publish the intentionally small entity set through MQTT Discovery."""

    LEGACY_DISCOVERY_ENTITIES = (
        ("binary_sensor", "doorbell"),
        ("binary_sensor", "awake"),
        ("binary_sensor", "message_service"),
        ("sensor", "last_event"),
        ("sensor", "doorbell_count"),
        ("sensor", "motion_count"),
        ("sensor", "last_image"),
        ("sensor", "last_image_status"),
        ("image", "last_snapshot"),
        ("image", "video"),
        ("camera", "video"),
    )

    def __init__(self, devices: dict[str, dict[str, str]]) -> None:
        service = supervisor_get("/services/mqtt")
        self.devices = devices
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"tuya-doorbell-bridge-{os.getpid()}",
            protocol=mqtt.MQTTv311,
        )
        username = service.get("username")
        if username:
            self.client.username_pw_set(str(username), str(service.get("password", "")))
        if bool(service.get("ssl")):
            self.client.tls_set()
        self.client.will_set(f"{TOPIC_PREFIX}/bridge/availability", "offline", qos=1, retain=True)
        self.client.connect(str(service["host"]), int(service.get("port", 1883)), keepalive=60)
        self.client.loop_start()
        self.client.publish(f"{TOPIC_PREFIX}/bridge/availability", "online", qos=1, retain=True)
        self._timers: dict[tuple[str, str], threading.Timer] = {}
        self._remove_legacy_discovery()
        self._publish_discovery()

    def close(self) -> None:
        for timer in self._timers.values():
            timer.cancel()
        self.client.publish(f"{TOPIC_PREFIX}/bridge/availability", "offline", qos=1, retain=True)
        self.client.loop_stop()
        self.client.disconnect()

    def base(self, device_id: str) -> str:
        return f"{TOPIC_PREFIX}/{slugify(device_id)}"

    def publish(self, topic: str, payload: Any, *, retain: bool = True) -> None:
        if not isinstance(payload, (str, bytes, bytearray)):
            payload = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        result = self.client.publish(topic, payload=payload, qos=1, retain=retain)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            LOGGER.warning("MQTT publish failed for %s with code %s", topic, result.rc)

    def _device_info(self, device_id: str) -> dict[str, Any]:
        return {
            "identifiers": [f"lsc_doorbell_{device_id}"],
            "name": self.devices[device_id]["name"],
            "manufacturer": "Tuya",
            "model": "Cloud doorbell event bridge",
        }

    def _config_topic(self, component: str, device_id: str, key: str) -> str:
        return f"{DISCOVERY_PREFIX}/{component}/{slugify(device_id)}/{key}/config"

    def _entity(self, component: str, device_id: str, key: str, payload: dict[str, Any]) -> None:
        payload = dict(payload)
        entity = {
            "name": payload.pop("name"),
            "unique_id": f"lsc_doorbell_{slugify(device_id)}_{key}",
            "availability_topic": f"{TOPIC_PREFIX}/bridge/availability",
            "payload_available": "online",
            "payload_not_available": "offline",
            "device": self._device_info(device_id),
        }
        entity.update(payload)
        self.publish(self._config_topic(component, device_id, key), entity)

    def _remove_legacy_discovery(self) -> None:
        for device_id in self.devices:
            for component, key in self.LEGACY_DISCOVERY_ENTITIES:
                self.publish(self._config_topic(component, device_id, key), "", retain=True)

    def _publish_discovery(self) -> None:
        for device_id in self.devices:
            base = self.base(device_id)
            self._entity(
                "binary_sensor",
                device_id,
                "motion",
                {
                    "name": "Motion",
                    "state_topic": f"{base}/motion/state",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device_class": "motion",
                },
            )
            self._entity(
                "binary_sensor",
                device_id,
                "pressed",
                {
                    "name": "Pressed",
                    "state_topic": f"{base}/pressed/state",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device_class": "occupancy",
                    "icon": "mdi:doorbell",
                },
            )
            self._entity(
                "image",
                device_id,
                "snapshot",
                {
                    "name": "Snapshot",
                    "image_topic": f"{base}/snapshot/image",
                    "content_type": "image/jpeg",
                    "json_attributes_topic": f"{base}/snapshot/attributes",
                },
            )
            self._entity(
                "sensor",
                device_id,
                "power_mode",
                {
                    "name": "Power mode",
                    "state_topic": f"{base}/power_mode",
                    "icon": "mdi:power-plug-battery",
                },
            )
            self._entity(
                "sensor",
                device_id,
                "battery",
                {
                    "name": "Battery",
                    "state_topic": f"{base}/battery",
                    "device_class": "battery",
                    "state_class": "measurement",
                    "unit_of_measurement": "%",
                },
            )
            self.publish(f"{base}/motion/state", "OFF")
            self.publish(f"{base}/pressed/state", "OFF")

    def set_state(self, device_id: str, key: str, value: Any) -> None:
        self.publish(f"{self.base(device_id)}/{key}", value)

    def pulse(self, device_id: str, kind: str, hold_seconds: float) -> None:
        state_topic = f"{self.base(device_id)}/{kind}/state"
        self.publish(state_topic, "ON", retain=False)
        timer_key = (device_id, kind)
        old = self._timers.pop(timer_key, None)
        if old:
            old.cancel()
        timer = threading.Timer(hold_seconds, lambda: self.publish(state_topic, "OFF", retain=False))
        timer.daemon = True
        self._timers[timer_key] = timer
        timer.start()

    def publish_snapshot(
        self,
        device_id: str,
        jpeg: bytes,
        *,
        source_camera: str,
        source_event: str,
        stream_url: str,
    ) -> None:
        base = self.base(device_id)
        self.publish(f"{base}/snapshot/image", jpeg, retain=True)
        self.publish(
            f"{base}/snapshot/attributes",
            {
                "source_camera": source_camera,
                "source_event": source_event,
                "stream_url": stream_url,
                "captured_at": int(time.time() * 1000),
            },
            retain=True,
        )


class Bridge:
    def __init__(self, options: dict[str, Any], camera_client: HomeAssistantCameraClient) -> None:
        self.options = options
        self.access_id = str(options["access_id"]).strip()
        self.access_secret = str(options["access_secret"]).strip()
        self.subscription = str(options["subscription_name"]).strip()
        self.environment = str(options.get("environment", "production"))
        self.data_center = str(options.get("data_center", "central_europe"))
        self.topic = f"{self.access_id}/out/{'event' if self.environment == 'production' else 'event-test'}"
        self.endpoint = PULSAR_ENDPOINTS[self.data_center]
        self.event_hold = float(options.get("event_hold_seconds", 5))
        self.dedupe = float(options.get("dedupe_seconds", 8))
        self.snapshot_delay = float(options.get("snapshot_delay_seconds", 2))
        self.snapshot_timeout = float(options.get("snapshot_timeout_seconds", 20))
        self.snapshot_on_press = bool(options.get("snapshot_on_press", True))
        self.snapshot_on_motion = bool(options.get("snapshot_on_motion", True))
        self.snapshot_periodic_enabled = bool(options.get("snapshot_periodic_enabled", False))
        self.snapshot_refresh_minutes = float(options.get("snapshot_refresh_minutes", 15))
        self.snapshot_retention_days = max(2, int(options.get("snapshot_retention_days", 2)))
        self.debug_payloads = bool(options.get("debug_payloads", False))
        self.devices = {
            str(item["device_id"]).strip(): {
                "name": str(item.get("name") or "Doorbell").strip(),
                "camera_entity": str(item.get("camera_entity") or "").strip(),
            }
            for item in options.get("devices", [])
            if isinstance(item, dict) and str(item.get("device_id", "")).strip()
        }
        if not self.devices:
            raise ValueError("Configure at least one device_id")
        for device_id, device in self.devices.items():
            if not device["camera_entity"].startswith("camera."):
                raise ValueError(
                    f"Configure a valid camera_entity for {device_id}; expected camera.<entity>"
                )

        self.camera_client = camera_client
        self.camera_client.timeout = self.snapshot_timeout
        self.mqtt = MqttPublisher(self.devices)
        self.snapshot_executor = ThreadPoolExecutor(max_workers=max(1, min(4, len(self.devices))))
        self.snapshot_timers: dict[str, threading.Timer] = {}
        self.snapshot_lock = threading.Lock()
        self.periodic_stop = threading.Event()
        # The periodic schedule is tracked only in RAM with a monotonic clock.
        # Snapshot files under /media/lsc_doorbell/snapshots are archive items only: deleting
        # the newest file (or the whole archive) cannot alter this state.
        self.periodic_state = threading.Condition()
        self.periodic_interval = max(60.0, self.snapshot_refresh_minutes * 60.0)
        now = time.monotonic()
        self.last_snapshot_attempt_at: dict[str, float] = {
            device_id: now - self.periodic_interval for device_id in self.devices
        }
        self.media_generation: dict[str, int] = {}
        self.last_events: dict[tuple[str, str], float] = {}
        self.refresh_threads: list[threading.Thread] = []
        SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
        self._cleanup_expired_snapshots()
        self._start_periodic_refresh()

    def close(self) -> None:
        self.periodic_stop.set()
        # Wake periodic workers that are sleeping on the in-memory condition.
        with self.periodic_state:
            self.periodic_state.notify_all()
        for thread in self.refresh_threads:
            thread.join(timeout=2)
        with self.snapshot_lock:
            for timer in self.snapshot_timers.values():
                timer.cancel()
            self.snapshot_timers.clear()
            for device_id in self.devices:
                self.media_generation[device_id] = self.media_generation.get(device_id, 0) + 1
        self.snapshot_executor.shutdown(wait=False, cancel_futures=True)
        self.mqtt.close()

    def _start_periodic_refresh(self) -> None:
        if not self.snapshot_periodic_enabled:
            LOGGER.info("Periodic snapshots are disabled")
            return
        LOGGER.info(
            "Periodic snapshots enabled every %.2f minute(s); "
            "schedule state is RAM-only (archive files are ignored)",
            self.periodic_interval / 60.0,
        )
        for device_id in self.devices:
            thread = threading.Thread(
                target=self._periodic_refresh_loop,
                args=(device_id,),
                daemon=True,
                name=f"snapshot-refresh-{slugify(device_id)}",
            )
            self.refresh_threads.append(thread)
            thread.start()

    def _remember_snapshot_attempt(self, device_id: str, when: float | None = None) -> None:
        """Remember snapshot timing in RAM and wake the periodic scheduler."""
        with self.periodic_state:
            self.last_snapshot_attempt_at[device_id] = (
                time.monotonic() if when is None else when
            )
            self.periodic_state.notify_all()

    def _periodic_refresh_loop(self, device_id: str) -> None:
        while not STOP.is_set() and not self.periodic_stop.is_set():
            with self.periodic_state:
                last_attempt = self.last_snapshot_attempt_at[device_id]
                due_at = last_attempt + self.periodic_interval
                remaining = due_at - time.monotonic()

                if remaining > 0:
                    self.periodic_state.wait(timeout=remaining)
                    continue

                # Reserve the next interval before submitting the capture. This
                # prevents rapid retries if the camera is asleep or unavailable.
                tick_at = time.monotonic()
                self.last_snapshot_attempt_at[device_id] = tick_at

            if STOP.is_set() or self.periodic_stop.is_set():
                break

            LOGGER.info(
                "Periodic snapshot tick for %s (RAM schedule)",
                self.devices[device_id]["name"],
            )
            self._submit_media(device_id, "periodic", None)

    def _submit_media(self, device_id: str, kind: str, generation: int | None) -> None:
        """Submit a capture without letting shutdown races kill timer threads."""
        try:
            self.snapshot_executor.submit(self._capture_media, device_id, kind, generation)
        except RuntimeError:
            LOGGER.debug(
                "Ignoring %s snapshot request for %s while the executor is shutting down",
                kind,
                self.devices[device_id]["name"],
            )

    def _store_snapshot(self, device_id: str, jpeg: bytes, kind: str) -> Path:
        folder = SNAPSHOT_ROOT / slugify(device_id)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time() * 1000)
        path = folder / f"{stamp}_{slugify(kind)}.jpg"
        path.write_bytes(jpeg)
        self._cleanup_expired_snapshots()
        return path

    def _cleanup_expired_snapshots(self) -> None:
        cutoff = time.time() - (self.snapshot_retention_days * 86400)
        if not SNAPSHOT_ROOT.exists():
            return
        for old in SNAPSHOT_ROOT.glob("*/*.jpg"):
            try:
                if old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                LOGGER.warning("Unable to inspect or remove expired snapshot %s", old)

    def _deduped(self, device_id: str, kind: str) -> bool:
        now = time.monotonic()
        key = (device_id, kind)
        previous = self.last_events.get(key)
        if previous is not None and now - previous < self.dedupe:
            return True
        self.last_events[key] = now
        return False

    def _schedule_media(self, device_id: str, kind: str) -> None:
        with self.snapshot_lock:
            previous = self.snapshot_timers.pop(device_id, None)
            if previous:
                previous.cancel()
            generation = self.media_generation.get(device_id, 0) + 1
            self.media_generation[device_id] = generation
            timer = threading.Timer(
                self.snapshot_delay,
                lambda: self._submit_media(device_id, kind, generation),
            )
            timer.daemon = True
            self.snapshot_timers[device_id] = timer
            timer.start()

    def _capture_media(self, device_id: str, kind: str, generation: int | None) -> None:
        camera_entity = self.devices[device_id]["camera_entity"]
        if generation is not None:
            with self.snapshot_lock:
                if self.media_generation.get(device_id) != generation:
                    return

        # Motion, pressed and periodic captures all reset the same RAM-only
        # interval. No file existence or mtime is read here.
        self._remember_snapshot_attempt(device_id)
        try:
            urls = self.camera_client.urls(camera_entity)
            jpeg = self.camera_client.capture(camera_entity)
            stored = self._store_snapshot(device_id, jpeg, kind)
            self.mqtt.publish_snapshot(
                device_id,
                jpeg,
                source_camera=camera_entity,
                source_event=kind,
                stream_url=urls.stream_url,
            )
            LOGGER.info(
                "Published %s-byte snapshot for %s after %s event using %s",
                len(jpeg),
                self.devices[device_id]["name"],
                kind,
                camera_entity,
            )
            LOGGER.debug("Stored snapshot at %s", stored)
        except CameraError as error:
            LOGGER.error(
                "Snapshot capture failed for %s using %s: %s",
                self.devices[device_id]["name"],
                camera_entity,
                error,
            )
        except Exception:
            LOGGER.exception("Unexpected snapshot error for %s", self.devices[device_id]["name"])

    def _handle_event(self, device_id: str, event: ParsedEvent) -> None:
        if event.kind == "battery":
            value = event.raw.get("value") if event.raw else "unknown"
            self.mqtt.set_state(device_id, "battery", value)
            return

        if event.kind == "power_mode":
            value = event.raw.get("value") if event.raw else None
            label = {"0": "battery", "1": "wired"}.get(str(value), str(value))
            self.mqtt.set_state(device_id, "power_mode", label)
            return

        if event.kind not in {"doorbell", "motion"}:
            return
        key = "pressed" if event.kind == "doorbell" else "motion"
        if self._deduped(device_id, event.kind):
            return

        self.mqtt.pulse(device_id, key, self.event_hold)
        should_capture = (event.kind == "doorbell" and self.snapshot_on_press) or (event.kind == "motion" and self.snapshot_on_motion)
        if should_capture:
            self._schedule_media(device_id, key)
        LOGGER.info("%s event from %s", key, self.devices[device_id]["name"])

    def run(self) -> None:
        retry = 2
        while not STOP.is_set():
            client = None
            consumer = None
            try:
                LOGGER.info(
                    "Connecting to Tuya: endpoint=%s topic=%s subscription=%s",
                    self.endpoint,
                    self.topic,
                    self.subscription,
                )
                client = pulsar.Client(
                    self.endpoint,
                    authentication=build_authentication(pulsar, self.access_id, self.access_secret),
                    tls_allow_insecure_connection=bool(self.options.get("tls_allow_insecure", True)),
                    operation_timeout_seconds=30,
                )
                consumer = client.subscribe(
                    self.topic,
                    self.subscription,
                    consumer_type=pulsar.ConsumerType.Failover,
                )
                retry = 2
                while not STOP.is_set():
                    try:
                        message = consumer.receive(timeout_millis=1000)
                    except pulsar.Timeout:
                        continue
                    try:
                        properties = message.properties() or {}
                        decrypted = decrypt_envelope(
                            message.data(), properties.get("em"), self.access_secret
                        )
                        if self.debug_payloads:
                            LOGGER.debug(
                                "Decrypted Tuya message: %s",
                                json.dumps(decrypted, ensure_ascii=False),
                            )
                        device_id = str(decrypted.get("devId", ""))
                        if device_id in self.devices:
                            for event in parse_message(
                                decrypted, DOORBELL_COMMANDS, MOTION_COMMANDS
                            ):
                                self._handle_event(device_id, event)
                        consumer.acknowledge(message)
                    except Exception:
                        LOGGER.exception("Unable to process a Tuya message")
                        consumer.negative_acknowledge(message)
            except Exception as error:
                LOGGER.error("Tuya consumer error: %s; retrying in %s seconds", error, retry)
                STOP.wait(retry)
                retry = min(retry * 2, 60)
            finally:
                if consumer is not None:
                    try:
                        consumer.close()
                    except Exception:
                        pass
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass


def validate_options(options: dict[str, Any]) -> None:
    for key in ("access_id", "access_secret", "subscription_name"):
        if not str(options.get(key) or "").strip():
            raise ValueError(f"Missing required option: {key}")
    if options.get("data_center") not in PULSAR_ENDPOINTS:
        raise ValueError("Unsupported data_center")
    if options.get("environment") not in {"production", "test"}:
        raise ValueError("Unsupported environment")
    devices = options.get("devices")
    if not isinstance(devices, list) or not any(
        isinstance(item, dict)
        and str(item.get("device_id") or "").strip()
        and str(item.get("camera_entity") or "").strip().startswith("camera.")
        for item in devices
    ):
        raise ValueError("Configure a Tuya device ID and a Home Assistant camera entity")


def main() -> None:
    initial = load_json(OPTIONS_PATH, {})
    level = getattr(logging, str(initial.get("log_level", "info")).upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    def stop_handler(_signum: int, _frame: Any) -> None:
        STOP.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    camera_client = HomeAssistantCameraClient(timeout=float(initial.get("snapshot_timeout_seconds", 20)))
    setup_ui = ConfigurationService(options_path=OPTIONS_PATH, camera_client=camera_client)
    setup_ui.start()

    bridge: Bridge | None = None
    try:
        options = load_json(OPTIONS_PATH, {})
        try:
            validate_options(options)
        except ValueError as error:
            LOGGER.warning("Configuration incomplete: %s", error)
            LOGGER.warning("Open the App Web UI to select Home Assistant entity IDs and save settings.")
            while not STOP.wait(1):
                pass
            return

        bridge = Bridge(options, camera_client)
        bridge.run()
    finally:
        if bridge is not None:
            bridge.close()
        setup_ui.close()


if __name__ == "__main__":
    main()
