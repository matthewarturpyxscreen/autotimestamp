"""Shared low-quota, opt-in Maintenance Mode control using Upstash REST.

This changes *application access*, not Streamlit Cloud server power/process state.
No customer data, files, session identifiers, or OCR output are stored.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import threading
import time
from urllib.parse import urlsplit
import urllib.error
import urllib.request

CACHE_SECONDS = 10.0
MAX_MESSAGE = 240
MIN_DURATION = 300
MAX_DURATION = 24 * 3600
_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], tuple[float, "MaintenanceStatus"]] = {}


class MaintenanceError(RuntimeError):
    """Sanitized control error (never contains token or upstream body)."""


@dataclass(frozen=True)
class MaintenanceStatus:
    enabled: bool = False
    message: str = ""
    until_ts: float = 0.0
    since_ts: float = 0.0
    available: bool = True
    detail: str = ""


def validate_namespace(app_id: str) -> str:
    if not isinstance(app_id, str) or not (1 <= len(app_id) <= 60):
        raise MaintenanceError("App ID tidak valid.")
    if not all(ch.isascii() and (ch.isalnum() or ch in "-_") for ch in app_id):
        raise MaintenanceError("App ID hanya boleh huruf, angka, - dan _.")
    return app_id


def maintenance_key(app_id: str) -> str:
    return f"pyx-monitor:{validate_namespace(app_id)}:maintenance"


def _validate_connection(url: str, token: str) -> tuple[str, str]:
    url = str(url or "").strip().rstrip("/")
    token = str(token or "").strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        raise MaintenanceError("PYX_METRICS_URL harus URL REST HTTPS Upstash yang valid.")
    if not token:
        raise MaintenanceError("Token Upstash belum diatur di Secrets.")
    return url, token


def _command(url: str, token: str, args: list, timeout: float = 2.5):
    url, token = _validate_connection(url, token)
    request = urllib.request.Request(
        url,
        data=json.dumps(args, separators=(",", ":")).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise MaintenanceError(f"Upstash HTTP {exc.code}. Periksa token dan URL database.") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise MaintenanceError("Koneksi Upstash gagal atau timeout.") from None
    except (ValueError, UnicodeDecodeError):
        raise MaintenanceError("Respons Upstash bukan JSON valid.") from None
    if not isinstance(result, dict) or "error" in result or "result" not in result:
        raise MaintenanceError("Upstash menolak perintah atau respons tidak valid.")
    return result["result"]


def _decode(raw: object, now_ts: float) -> MaintenanceStatus:
    if raw is None:
        return MaintenanceStatus()
    if not isinstance(raw, str):
        raise MaintenanceError("Data Maintenance Mode di Upstash tidak valid.")
    try:
        state = json.loads(raw)
    except (ValueError, TypeError):
        raise MaintenanceError("Data Maintenance Mode tidak dapat dibaca.") from None
    if not isinstance(state, dict):
        raise MaintenanceError("Format Maintenance Mode tidak valid.")
    try:
        until_ts = float(state.get("until_ts", 0))
        since_ts = float(state.get("since_ts", 0))
    except (ValueError, TypeError):
        raise MaintenanceError("Waktu Maintenance Mode tidak valid.") from None
    if not (0 < until_ts < 10**11) or not (0 < since_ts < 10**11):
        raise MaintenanceError("Waktu Maintenance Mode di luar batas.")
    message = str(state.get("message") or "Pemeliharaan sistem sedang berlangsung.")[:MAX_MESSAGE]
    enabled = bool(state.get("enabled") is True and until_ts > now_ts)
    return MaintenanceStatus(enabled=enabled, message=message if enabled else "", until_ts=until_ts if enabled else 0.0, since_ts=since_ts if enabled else 0.0)


def read_status(url: str, token: str, app_id: str = "timestamp-pyx", *, force: bool = False, at_time: float | None = None) -> MaintenanceStatus:
    """Cache one small GET per process for several browser sessions.

    On a temporary network failure, retain last-known *active* maintenance
    until its own expiry, so short Upstash disruptions do not reopen the app.
    First-ever reads fail open to protect core app availability; monitor warns.
    """
    now_ts = float(at_time if at_time is not None else time.time())
    key = maintenance_key(app_id)
    cache_key = (str(url), key)
    now_mono = time.monotonic()
    # A single in-process lock covers the network miss: many Streamlit
    # fragments waking at once must NOT make one REST request per browser.
    with _LOCK:
        cached = _CACHE.get(cache_key)
        if cached and not force and cached[0] > now_mono:
            state = cached[1]
            if state.enabled and state.until_ts <= now_ts:
                return MaintenanceStatus()
            return state
        try:
            raw = _command(url, token, ["GET", key])
            status = _decode(raw, now_ts)
        except MaintenanceError as err:
            if cached:
                prior = cached[1]
                if prior.enabled and prior.until_ts > now_ts:
                    status = replace(prior, available=False, detail=str(err))
                else:
                    status = MaintenanceStatus(available=False, detail=str(err))
            else:
                status = MaintenanceStatus(available=False, detail=str(err))
        _CACHE[cache_key] = (now_mono + (30.0 if not status.available else CACHE_SECONDS), status)
        if len(_CACHE) > 32:
            _CACHE.pop(next(iter(_CACHE)))
        return status


def set_status(url: str, token: str, app_id: str, *, enabled: bool, message: str = "", duration_seconds: int = 3600, at_time: float | None = None) -> None:
    """Atomic SET+EX for active maintenance; DEL for normal operation.

    A mandatory TTL guarantees auto-restore even if the monitor disappears.
    """
    key = maintenance_key(app_id)
    if enabled:
        duration_seconds = int(duration_seconds)
        if not MIN_DURATION <= duration_seconds <= MAX_DURATION:
            raise MaintenanceError("Durasi maintenance harus antara 5 menit dan 24 jam.")
        cleaned_message = " ".join(str(message or "").split())[:MAX_MESSAGE]
        if not cleaned_message:
            cleaned_message = "Sistem sedang dalam pemeliharaan. Silakan coba kembali nanti."
        now_ts = float(at_time if at_time is not None else time.time())
        state = {"enabled": True, "message": cleaned_message, "since_ts": int(now_ts), "until_ts": int(now_ts + duration_seconds)}
        result = _command(url, token, ["SET", key, json.dumps(state, ensure_ascii=False, separators=(",", ":")), "EX", duration_seconds])
        if result != "OK":
            raise MaintenanceError("Upstash tidak mengonfirmasi aktivasi maintenance.")
    else:
        result = _command(url, token, ["DEL", key])
        if isinstance(result, bool) or not isinstance(result, int) or result < 0:
            raise MaintenanceError("Upstash tidak mengonfirmasi penonaktifan maintenance.")
    with _LOCK:
        _CACHE.pop((str(url), key), None)


__all__ = ["MaintenanceError", "MaintenanceStatus", "read_status", "set_status", "maintenance_key", "validate_namespace"]
