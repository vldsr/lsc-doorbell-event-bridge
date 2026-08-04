"""Ingress Web UI for configuration and snapshot archive management."""
from __future__ import annotations

import io
import json
import logging
import mimetypes
import os
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests

from ha_camera import CameraError, HomeAssistantCameraClient

LOGGER = logging.getLogger("lsc_doorbell_bridge.config")
SUPERVISOR_URL = "http://supervisor"
SNAPSHOT_ROOT = Path("/data/snapshots")

HTML = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LSC Doorbell Event Bridge</title><style>
:root{color-scheme:light dark;--accent:#03a9f4;--card:rgba(127,127,127,.10);--line:rgba(127,127,127,.28)}*{box-sizing:border-box}body{margin:0;font-family:Roboto,Arial,sans-serif;background:var(--primary-background-color,#fafafa);color:var(--primary-text-color,#202124)}main{max-width:1100px;margin:auto;padding:24px 18px 48px}header{display:flex;gap:16px;align-items:flex-start;justify-content:space-between}h1{font-size:1.7rem;margin:0 0 8px}h2{margin-top:0}.intro,small{opacity:.78;line-height:1.45}section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.wide{grid-column:1/-1}label{display:block;font-weight:600;margin-bottom:6px}input,select,button{font:inherit}input,select{width:100%;padding:11px;border:1px solid var(--line);border-radius:9px;background:transparent;color:inherit}.language{width:auto;min-width:150px}.toggle{display:flex;align-items:center;justify-content:space-between;gap:14px;border:1px solid var(--line);padding:12px;border-radius:10px}.toggle input{width:22px;height:22px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}button{border:0;border-radius:9px;padding:11px 16px;background:var(--accent);color:white;cursor:pointer}button.secondary{background:rgba(127,127,127,.35)}button.danger{background:#d32f2f}.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:14px}.shot{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:rgba(0,0,0,.04)}.shot img{display:block;width:100%;aspect-ratio:16/10;object-fit:cover}.shot .meta{padding:9px;font-size:.86rem}.shot .pick{position:absolute;margin:8px;width:22px;height:22px}.empty{opacity:.7;padding:22px;text-align:center}.success{color:#2e7d32}.error{color:#c62828}@media(max-width:700px){.grid{grid-template-columns:1fr}.wide{grid-column:auto}header{display:block}.language{width:100%;margin:10px 0}}
</style></head><body><main><header><div><h1>LSC Doorbell Event Bridge 1.0.0</h1><p class="intro" data-i18n="intro"></p></div><div><label data-i18n="language"></label><select id="language" class="language"><option value="en">English</option><option value="it">Italiano</option><option value="de">Deutsch</option><option value="fr">Français</option><option value="es">Español</option></select></div></header>
<form id="form"><section><h2 data-i18n="tuya_device"></h2><div class="grid"><div><label data-i18n="access_id"></label><input id="access_id" required></div><div><label data-i18n="access_secret"></label><input id="access_secret" type="password"></div><div><label data-i18n="subscription"></label><input id="subscription_name" required></div><div><label data-i18n="data_center"></label><select id="data_center"><option value="central_europe">Central Europe</option><option value="america">America</option><option value="china">China</option><option value="india">India</option></select></div><div><label data-i18n="environment"></label><select id="environment"><option value="production">Production</option><option value="test">Test</option></select></div><div><label data-i18n="doorbell_name"></label><input id="name" value="Doorbell"></div><div><label data-i18n="device_id"></label><input id="device_id" list="device_ids" required><datalist id="device_ids"></datalist></div><div><label data-i18n="camera"></label><input id="camera_entity" list="camera_entities" required><datalist id="camera_entities"></datalist></div></div></section>
<section><h2 data-i18n="snapshot_triggers"></h2><div class="grid"><div class="toggle"><span><b data-i18n="on_press"></b><br><small data-i18n="on_press_desc"></small></span><input id="snapshot_on_press" type="checkbox"></div><div class="toggle"><span><b data-i18n="on_motion"></b><br><small data-i18n="on_motion_desc"></small></span><input id="snapshot_on_motion" type="checkbox"></div><div class="toggle"><span><b data-i18n="periodic"></b><br><small data-i18n="periodic_desc"></small></span><input id="snapshot_periodic_enabled" type="checkbox"></div><div><label data-i18n="interval"></label><input id="snapshot_refresh_minutes" type="number" min="1" max="1440" step="1" value="15"></div><div><label data-i18n="delay"></label><input id="snapshot_delay_seconds" type="number" min="0" max="30" step="0.5" value="2"></div><div><label data-i18n="hold"></label><input id="event_hold_seconds" type="number" min="1" max="60" step="1" value="5"></div></div></section>
<section><h2 data-i18n="archive"></h2><div class="grid"><div><label data-i18n="retention"></label><input id="snapshot_retention_days" type="number" min="2" max="3650" step="1" value="2"><small data-i18n="retention_desc"></small></div></div></section>
<button id="save" type="submit" data-i18n="save"></button><div id="message"></div></form>
<section><h2 data-i18n="saved_photos"></h2><div class="actions"><button class="secondary" id="select_all" type="button" data-i18n="select_all"></button><button class="secondary" id="clear_selection" type="button" data-i18n="clear"></button><button id="download_selected" type="button" data-i18n="download"></button><button class="danger" id="delete_selected" type="button" data-i18n="delete"></button></div><p class="intro" data-i18n="newest"></p><div id="gallery" class="gallery"></div></section>
<script>
const $=id=>document.getElementById(id);let currentConfig={};const supported=['en','it','de','fr','es'];
const TRANSLATIONS={"en":{"intro":"Configure the App, snapshot triggers and archive retention entirely from this Web UI.","tuya_device":"Tuya and device","access_id":"Access ID","access_secret":"Access Secret","subscription":"Subscription name","data_center":"Data center","environment":"Environment","doorbell_name":"Doorbell name","device_id":"Tuya device ID","camera":"Home Assistant camera","snapshot_triggers":"Snapshot triggers","on_press":"Snapshot on press","on_press_desc":"Capture after a doorbell press.","on_motion":"Snapshot on motion","on_motion_desc":"Capture after a motion event.","periodic":"Periodic snapshots","periodic_desc":"Capture automatically at the configured interval.","interval":"Periodic interval (minutes)","delay":"Delay after event (seconds)","hold":"Event state duration (seconds)","archive":"Photo archive","retention":"Retention (days)","retention_desc":"All photos are kept until they are older than this value. Minimum: 2 days.","save":"Save and restart App","saved_photos":"Saved photos","select_all":"Select all","clear":"Clear selection","download":"Download selected","delete":"Delete selected","newest":"Newest first. Select one or more photos to download or delete them.","empty":"No snapshots yet.","saved":"Saved. The App is restarting.","required":"Required","secret_saved":"Saved — leave blank to keep","select_photo":"Select at least one photo.","confirm_delete":"Delete {count} selected photo(s)?","load_error":"Unable to load configuration: {error}","save_error":"Save failed: {error}","language":"Language","auto":"Automatic"},"it":{"intro":"Configura App, trigger degli snapshot e conservazione dell’archivio interamente dalla Web UI.","tuya_device":"Tuya e dispositivo","access_id":"Access ID","access_secret":"Access Secret","subscription":"Nome sottoscrizione","data_center":"Centro dati","environment":"Ambiente","doorbell_name":"Nome campanello","device_id":"ID dispositivo Tuya","camera":"Camera Home Assistant","snapshot_triggers":"Trigger snapshot","on_press":"Snapshot alla pressione","on_press_desc":"Scatta dopo la pressione del campanello.","on_motion":"Snapshot al movimento","on_motion_desc":"Scatta dopo un evento di movimento.","periodic":"Snapshot periodici","periodic_desc":"Scatta automaticamente all’intervallo configurato.","interval":"Intervallo periodico (minuti)","delay":"Ritardo dopo evento (secondi)","hold":"Durata stato evento (secondi)","archive":"Archivio fotografico","retention":"Conservazione (giorni)","retention_desc":"Tutte le foto vengono conservate finché non superano questo valore. Minimo: 2 giorni.","save":"Salva e riavvia App","saved_photos":"Foto salvate","select_all":"Seleziona tutto","clear":"Annulla selezione","download":"Scarica selezionate","delete":"Elimina selezionate","newest":"Più recenti prima. Seleziona una o più foto da scaricare o eliminare.","empty":"Nessuno snapshot disponibile.","saved":"Salvato. L’App si sta riavviando.","required":"Obbligatorio","secret_saved":"Salvato — lascia vuoto per mantenerlo","select_photo":"Seleziona almeno una foto.","confirm_delete":"Eliminare {count} foto selezionate?","load_error":"Impossibile caricare la configurazione: {error}","save_error":"Salvataggio non riuscito: {error}","language":"Lingua","auto":"Automatico"},"de":{"intro":"App, Snapshot-Auslöser und Archivaufbewahrung vollständig über diese Weboberfläche konfigurieren.","tuya_device":"Tuya und Gerät","access_id":"Access-ID","access_secret":"Access Secret","subscription":"Abonnementname","data_center":"Rechenzentrum","environment":"Umgebung","doorbell_name":"Name der Türklingel","device_id":"Tuya-Geräte-ID","camera":"Home-Assistant-Kamera","snapshot_triggers":"Snapshot-Auslöser","on_press":"Snapshot bei Tastendruck","on_press_desc":"Nach einem Klingeldruck aufnehmen.","on_motion":"Snapshot bei Bewegung","on_motion_desc":"Nach einer Bewegung aufnehmen.","periodic":"Periodische Snapshots","periodic_desc":"Automatisch im eingestellten Intervall aufnehmen.","interval":"Intervall (Minuten)","delay":"Verzögerung nach Ereignis (Sekunden)","hold":"Ereignisdauer (Sekunden)","archive":"Fotoarchiv","retention":"Aufbewahrung (Tage)","retention_desc":"Fotos bleiben bis zum Ablauf dieser Frist gespeichert. Minimum: 2 Tage.","save":"Speichern und App neu starten","saved_photos":"Gespeicherte Fotos","select_all":"Alle auswählen","clear":"Auswahl aufheben","download":"Auswahl herunterladen","delete":"Auswahl löschen","newest":"Neueste zuerst. Fotos zum Herunterladen oder Löschen auswählen.","empty":"Noch keine Snapshots.","saved":"Gespeichert. Die App wird neu gestartet.","required":"Erforderlich","secret_saved":"Gespeichert — leer lassen, um es beizubehalten","select_photo":"Mindestens ein Foto auswählen.","confirm_delete":"{count} ausgewählte Fotos löschen?","load_error":"Konfiguration konnte nicht geladen werden: {error}","save_error":"Speichern fehlgeschlagen: {error}","language":"Sprache","auto":"Automatisch"},"fr":{"intro":"Configurez l’App, les déclencheurs et la conservation des photos depuis cette interface Web.","tuya_device":"Tuya et appareil","access_id":"Access ID","access_secret":"Access Secret","subscription":"Nom de l’abonnement","data_center":"Centre de données","environment":"Environnement","doorbell_name":"Nom de la sonnette","device_id":"ID appareil Tuya","camera":"Caméra Home Assistant","snapshot_triggers":"Déclencheurs de snapshot","on_press":"Snapshot à l’appui","on_press_desc":"Capturer après un appui sur la sonnette.","on_motion":"Snapshot au mouvement","on_motion_desc":"Capturer après un mouvement.","periodic":"Snapshots périodiques","periodic_desc":"Capturer automatiquement à l’intervalle configuré.","interval":"Intervalle (minutes)","delay":"Délai après événement (secondes)","hold":"Durée de l’état événement (secondes)","archive":"Archive photo","retention":"Conservation (jours)","retention_desc":"Les photos sont conservées jusqu’à dépasser cette durée. Minimum : 2 jours.","save":"Enregistrer et redémarrer l’App","saved_photos":"Photos enregistrées","select_all":"Tout sélectionner","clear":"Effacer la sélection","download":"Télécharger la sélection","delete":"Supprimer la sélection","newest":"Plus récentes en premier. Sélectionnez des photos à télécharger ou supprimer.","empty":"Aucun snapshot.","saved":"Enregistré. L’App redémarre.","required":"Requis","secret_saved":"Enregistré — laisser vide pour conserver","select_photo":"Sélectionnez au moins une photo.","confirm_delete":"Supprimer {count} photo(s) sélectionnée(s) ?","load_error":"Impossible de charger la configuration : {error}","save_error":"Échec de l’enregistrement : {error}","language":"Langue","auto":"Automatique"},"es":{"intro":"Configure la App, los disparadores y la retención del archivo desde esta Web UI.","tuya_device":"Tuya y dispositivo","access_id":"Access ID","access_secret":"Access Secret","subscription":"Nombre de suscripción","data_center":"Centro de datos","environment":"Entorno","doorbell_name":"Nombre del timbre","device_id":"ID del dispositivo Tuya","camera":"Cámara de Home Assistant","snapshot_triggers":"Disparadores de captura","on_press":"Captura al pulsar","on_press_desc":"Capturar después de pulsar el timbre.","on_motion":"Captura por movimiento","on_motion_desc":"Capturar después de detectar movimiento.","periodic":"Capturas periódicas","periodic_desc":"Capturar automáticamente con el intervalo configurado.","interval":"Intervalo (minutos)","delay":"Retardo tras evento (segundos)","hold":"Duración del evento (segundos)","archive":"Archivo fotográfico","retention":"Conservación (días)","retention_desc":"Las fotos se conservan hasta superar este valor. Mínimo: 2 días.","save":"Guardar y reiniciar App","saved_photos":"Fotos guardadas","select_all":"Seleccionar todo","clear":"Borrar selección","download":"Descargar seleccionadas","delete":"Eliminar seleccionadas","newest":"Más recientes primero. Selecciona fotos para descargar o eliminar.","empty":"Todavía no hay capturas.","saved":"Guardado. La App se está reiniciando.","required":"Obligatorio","secret_saved":"Guardado — déjalo vacío para conservarlo","select_photo":"Selecciona al menos una foto.","confirm_delete":"¿Eliminar {count} foto(s) seleccionada(s)?","load_error":"No se pudo cargar la configuración: {error}","save_error":"Error al guardar: {error}","language":"Idioma","auto":"Automático"}};
let I18N=TRANSLATIONS.en;
function resolveLang(value){return supported.includes(value)?value:'en'}
async function req(u,o){const r=await fetch(u,o);if((r.headers.get('content-type')||'').includes('application/json')){const b=await r.json();if(!r.ok)throw new Error(b.error||r.statusText);return b}if(!r.ok)throw new Error(r.statusText);return r}
function setLanguage(value){const lang=resolveLang(value);I18N=TRANSLATIONS[lang]||TRANSLATIONS.en;document.documentElement.lang=lang;$('language').value=lang;document.querySelectorAll('[data-i18n]').forEach(el=>{const k=el.dataset.i18n;el.textContent=I18N[k]||TRANSLATIONS.en[k]||k});if(currentConfig.has_access_secret)$('access_secret').placeholder=I18N.secret_saved||TRANSLATIONS.en.secret_saved;else $('access_secret').placeholder=I18N.required||TRANSLATIONS.en.required;loadGallery()}
function tr(k,vars={}){let s=I18N[k]||k;Object.entries(vars).forEach(([a,b])=>s=s.replace(`{${a}}`,b));return s}function msg(t,ok=false){const m=$('message');m.textContent=t;m.className=ok?'success':'error'}
async function load(){try{const [c,e]=await Promise.all([req('api/config'),req('api/entities')]);currentConfig=c;const cl=$('camera_entities'),dl=$('device_ids');(e.cameras||[]).forEach(x=>{const o=document.createElement('option');o.value=x.entity_id;o.label=`${x.name} — ${x.entity_id}`;cl.appendChild(o);(x.device_id_candidates||[]).forEach(v=>{const d=document.createElement('option');d.value=v;dl.appendChild(d)})});['access_id','subscription_name','data_center','environment','name','device_id','camera_entity','event_hold_seconds','snapshot_delay_seconds','snapshot_refresh_minutes','snapshot_retention_days'].forEach(k=>{if(c[k]!==undefined)$(k).value=c[k]});['snapshot_on_press','snapshot_on_motion','snapshot_periodic_enabled'].forEach(k=>$(k).checked=!!c[k]);$('language').value=resolveLang(c.webui_language||'en');setLanguage($('language').value)}catch(e){setLanguage('en');msg(tr('load_error',{error:e.message}))}}
function selected(){return [...document.querySelectorAll('.pick:checked')].map(x=>x.value)}
async function loadGallery(){try{const d=await req('api/snapshots');const g=$('gallery');g.innerHTML='';(d.snapshots||[]).forEach(s=>{const card=document.createElement('div');card.className='shot';const cb=document.createElement('input');cb.type='checkbox';cb.className='pick';cb.value=s.id;const a=document.createElement('a');a.href=s.url;a.target='_blank';const i=document.createElement('img');i.src=s.url+`?t=${s.mtime}`;i.loading='lazy';a.appendChild(i);const cap=document.createElement('div');cap.className='meta';cap.textContent=`${new Date(s.mtime*1000).toLocaleString()} · ${Math.round(s.size/1024)} KB`;card.append(cb,a,cap);g.appendChild(card)});if(!(d.snapshots||[]).length)g.innerHTML=`<div class="empty">${tr('empty')}</div>`}catch(e){}}
$('language').addEventListener('change',()=>setLanguage($('language').value));
$('form').addEventListener('submit',async ev=>{ev.preventDefault();const p={};['access_id','access_secret','subscription_name','data_center','environment','name','device_id','camera_entity'].forEach(k=>p[k]=$(k).value.trim());['event_hold_seconds','snapshot_delay_seconds','snapshot_refresh_minutes','snapshot_retention_days'].forEach(k=>p[k]=Number($(k).value));['snapshot_on_press','snapshot_on_motion','snapshot_periodic_enabled'].forEach(k=>p[k]=$(k).checked);p.webui_language=$('language').value;try{await req('api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});msg(tr('saved'),true)}catch(e){msg(tr('save_error',{error:e.message}))}});
$('select_all').onclick=()=>document.querySelectorAll('.pick').forEach(x=>x.checked=true);$('clear_selection').onclick=()=>document.querySelectorAll('.pick').forEach(x=>x.checked=false);
$('delete_selected').onclick=async()=>{const ids=selected();if(!ids.length)return alert(tr('select_photo'));if(!confirm(tr('confirm_delete',{count:ids.length})))return;try{await req('api/snapshots/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})});loadGallery()}catch(e){alert(e.message)}};
$('download_selected').onclick=async()=>{const ids=selected();if(!ids.length)return alert(tr('select_photo'));const r=await fetch('api/snapshots/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})});if(!r.ok){const b=await r.json().catch(()=>({}));return alert(b.error||r.statusText)}const blob=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='lsc-doorbell-snapshots.zip';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
load();setInterval(loadGallery,15000);
</script></main></body></html>'''


class ConfigurationService:
    def __init__(self, *, options_path: Path, camera_client: HomeAssistantCameraClient, host: str = "0.0.0.0", port: int = 8099):
        self.options_path = options_path
        self.camera_client = camera_client
        self.host = host
        self.port = int(port)
        self.httpd = None
        self.thread = None

    def load_options(self) -> dict[str, Any]:
        try:
            data = json.loads(self.options_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def public_config(options: dict[str, Any]) -> dict[str, Any]:
        devices = options.get("devices") if isinstance(options.get("devices"), list) else []
        device = devices[0] if devices and isinstance(devices[0], dict) else {}
        return {
            "access_id": options.get("access_id", ""),
            "has_access_secret": bool(str(options.get("access_secret") or "").strip()),
            "subscription_name": options.get("subscription_name", ""),
            "data_center": options.get("data_center", "central_europe"),
            "environment": options.get("environment", "production"),
            "name": device.get("name", "Doorbell"),
            "device_id": device.get("device_id", ""),
            "camera_entity": device.get("camera_entity", ""),
            "event_hold_seconds": options.get("event_hold_seconds", 5),
            "snapshot_delay_seconds": options.get("snapshot_delay_seconds", 2),
            "snapshot_on_press": options.get("snapshot_on_press", True),
            "snapshot_on_motion": options.get("snapshot_on_motion", True),
            "snapshot_periodic_enabled": options.get("snapshot_periodic_enabled", False),
            "snapshot_refresh_minutes": options.get("snapshot_refresh_minutes", 15),
            "snapshot_retention_days": options.get("snapshot_retention_days", 2),
            "webui_language": options.get("webui_language", "en"),
        }

    def _snapshot_path(self, snapshot_id: str) -> Path:
        parts = snapshot_id.split("/", 1)
        if len(parts) != 2:
            raise ValueError("Invalid snapshot ID")
        target = (SNAPSHOT_ROOT / parts[0] / parts[1]).resolve()
        if SNAPSHOT_ROOT.resolve() not in target.parents or target.suffix.lower() not in {".jpg", ".jpeg"}:
            raise ValueError("Invalid snapshot path")
        return target

    def snapshots(self) -> list[dict[str, Any]]:
        items = []
        if SNAPSHOT_ROOT.exists():
            for path in SNAPSHOT_ROOT.glob("*/*.jpg"):
                try:
                    stat = path.stat()
                    items.append((stat.st_mtime, stat.st_size, path))
                except OSError:
                    pass
        items.sort(reverse=True, key=lambda item: item[0])
        return [{"id": f"{p.parent.name}/{p.name}", "name": p.name, "mtime": m, "size": size, "url": f"snapshot/{p.parent.name}/{p.name}"} for m, size, p in items]

    def save(self, incoming: dict[str, Any]) -> None:
        current = self.load_options()
        secret = str(incoming.get("access_secret") or "").strip() or str(current.get("access_secret") or "").strip()
        required = {
            "access_id": str(incoming.get("access_id") or "").strip(),
            "access_secret": secret,
            "subscription_name": str(incoming.get("subscription_name") or "").strip(),
            "device_id": str(incoming.get("device_id") or "").strip(),
            "camera_entity": str(incoming.get("camera_entity") or "").strip(),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError("Missing required fields: " + ", ".join(missing))
        cameras = {item["entity_id"] for item in self.camera_client.list_cameras()}
        if required["camera_entity"] not in cameras:
            raise ValueError("Camera entity not found in Home Assistant")
        refresh = float(incoming.get("snapshot_refresh_minutes", 15))
        if refresh < 1 or refresh > 1440:
            raise ValueError("Periodic interval must be between 1 and 1440 minutes")
        retention = int(incoming.get("snapshot_retention_days", 2))
        if retention < 2 or retention > 3650:
            raise ValueError("Retention must be between 2 and 3650 days")
        options = {
            "access_id": required["access_id"], "access_secret": required["access_secret"],
            "subscription_name": required["subscription_name"],
            "data_center": str(incoming.get("data_center") or "central_europe"),
            "environment": str(incoming.get("environment") or "production"),
            "devices": [{"device_id": required["device_id"], "name": str(incoming.get("name") or "Doorbell").strip() or "Doorbell", "camera_entity": required["camera_entity"]}],
            "event_hold_seconds": float(incoming.get("event_hold_seconds", 5)),
            "dedupe_seconds": float(current.get("dedupe_seconds", 8)),
            "snapshot_delay_seconds": float(incoming.get("snapshot_delay_seconds", 2)),
            "snapshot_timeout_seconds": float(current.get("snapshot_timeout_seconds", 20)),
            "snapshot_on_press": bool(incoming.get("snapshot_on_press", True)),
            "snapshot_on_motion": bool(incoming.get("snapshot_on_motion", True)),
            "snapshot_periodic_enabled": bool(incoming.get("snapshot_periodic_enabled", False)),
            "snapshot_refresh_minutes": refresh,
            "snapshot_retention_days": retention,
            "tls_allow_insecure": bool(current.get("tls_allow_insecure", True)),
            "debug_payloads": bool(current.get("debug_payloads", False)),
            "log_level": str(current.get("log_level", "info")),
            "webui_language": str(incoming.get("webui_language") or current.get("webui_language", "en")),
        }
        token = os.environ.get("SUPERVISOR_TOKEN", "")
        response = requests.post(f"{SUPERVISOR_URL}/addons/self/options", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json={"options": options}, timeout=20)
        response.raise_for_status()
        def restart() -> None:
            time.sleep(1.2)
            try:
                requests.post(f"{SUPERVISOR_URL}/addons/self/restart", headers={"Authorization": f"Bearer {token}"}, timeout=10)
            except requests.RequestException:
                LOGGER.exception("Unable to restart App")
        threading.Thread(target=restart, daemon=True).start()

    def start(self) -> None:
        service = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args): LOGGER.debug("Ingress: " + fmt, *args)
            def _json(self, status, payload):
                body = json.dumps(payload, separators=(",", ":")).encode()
                self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def _incoming(self):
                length = int(self.headers.get("Content-Length", "0")); return json.loads(self.rfile.read(length) or b"{}")
            def do_GET(self):
                clean = (self.path.split("?", 1)[0].rstrip("/") or "/")
                if clean == "/health": return self._json(200, {"status": "ok"})
                if clean == "/api/config": return self._json(200, service.public_config(service.load_options()))
                if clean == "/api/entities":
                    try: return self._json(200, {"cameras": service.camera_client.list_cameras()})
                    except CameraError as error: return self._json(502, {"error": str(error)})
                if clean == "/api/snapshots": return self._json(200, {"snapshots": service.snapshots()})
                if clean.startswith("/locales/"):
                    lang = clean.rsplit("/", 1)[-1]
                    if lang in {"en.json", "it.json", "de.json", "fr.json", "es.json"}:
                        path = Path(__file__).parent / "web" / "locales" / lang
                        try:
                            data = path.read_bytes(); self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Cache-Control", "no-cache"); self.send_header("Content-Length", str(len(data))); self.end_headers(); return self.wfile.write(data)
                        except OSError: return self._json(404, {"error": "Locale not found"})
                if clean.startswith("/snapshot/"):
                    parts = [unquote(x) for x in clean.split("/") if x]
                    if len(parts) == 3:
                        try:
                            target = service._snapshot_path(f"{parts[1]}/{parts[2]}")
                            data = target.read_bytes(); self.send_response(200); self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "image/jpeg"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(data))); self.end_headers(); return self.wfile.write(data)
                        except (OSError, ValueError): return self._json(404, {"error": "Snapshot not found"})
                if clean == "/":
                    body = HTML.encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); return self.wfile.write(body)
                return self._json(404, {"error": "Not found"})
            def do_POST(self):
                clean = self.path.split("?", 1)[0].rstrip("/")
                try:
                    incoming = self._incoming()
                    if clean == "/api/config": service.save(incoming); return self._json(200, {"saved": True, "restarting": True})
                    if clean == "/api/snapshots/delete":
                        deleted = 0
                        for snapshot_id in incoming.get("ids", []):
                            try: service._snapshot_path(str(snapshot_id)).unlink(); deleted += 1
                            except (OSError, ValueError): pass
                        return self._json(200, {"deleted": deleted})
                    if clean == "/api/snapshots/download":
                        selected = []
                        for snapshot_id in incoming.get("ids", []):
                            try:
                                path = service._snapshot_path(str(snapshot_id))
                                if path.is_file(): selected.append(path)
                            except ValueError: pass
                        if not selected: return self._json(400, {"error": "No valid photos selected"})
                        buffer = io.BytesIO()
                        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                            for path in selected: archive.write(path, arcname=f"{path.parent.name}/{path.name}")
                        payload = buffer.getvalue(); self.send_response(200); self.send_header("Content-Type", "application/zip"); self.send_header("Content-Disposition", 'attachment; filename="lsc-doorbell-snapshots.zip"'); self.send_header("Content-Length", str(len(payload))); self.end_headers(); return self.wfile.write(payload)
                    return self._json(404, {"error": "Not found"})
                except Exception as error:
                    LOGGER.exception("Web UI request failed")
                    return self._json(400, {"error": str(error)})
        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start(); LOGGER.info("Configuration UI listening on port %s", self.port)

    def close(self) -> None:
        if self.httpd: self.httpd.shutdown(); self.httpd.server_close()
