"""PYX Mission Control: lean Redis/Upstash maintenance state, V1.5.0.

Schedule activation/expiry are timestamp-based, not a background worker.
This flag gates Streamlit UI only; it does not shut down Streamlit Cloud.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

CACHE_SECONDS = 9.0
ERROR_CACHE_SECONDS = 30.0
MIN_DURATION = 300
MAX_DURATION = 24 * 3600
MAX_SCHEDULE_AHEAD = 7 * 86400
MAX_WARNING = 3600
MAX_MESSAGE = 240
_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], tuple[float, "MaintenanceStatus"]] = {}


class MaintenanceError(RuntimeError):
    """A sanitized error safe to show to admins."""


@dataclass(frozen=True)
class MaintenanceStatus:
    enabled: bool = False
    message: str = ""
    until_ts: float = 0.0
    since_ts: float = 0.0
    available: bool = True
    detail: str = ""
    starts_ts: float = 0.0
    warning_seconds: int = 0
    phase: str = "normal"  # normal, scheduled, warning, active


def validate_namespace(app_id: str) -> str:
    if not isinstance(app_id, str) or not 1 <= len(app_id) <= 60:
        raise MaintenanceError("App ID tidak valid.")
    if not all(ch.isascii() and (ch.isalnum() or ch in "-_" ) for ch in app_id):
        raise MaintenanceError("App ID hanya boleh huruf, angka, - dan _.")
    return app_id


def maintenance_key(app_id: str) -> str:
    return f"pyx-monitor:{validate_namespace(app_id)}:maintenance"


def maintenance_audit_key(app_id: str) -> str:
    return f"pyx-monitor:{validate_namespace(app_id)}:maintenance:audit"


def _validate_connection(url: str, token: str) -> tuple[str, str]:
    url = str(url or "").strip().rstrip("/")
    token = str(token or "").strip()
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ("", "/")):
        raise MaintenanceError("PYX_METRICS_URL harus URL REST HTTPS Upstash yang valid.")
    if not token:
        raise MaintenanceError("Token Upstash belum diatur di Secrets.")
    return url, token


def _command(url: str, token: str, args: list, timeout: float = 2.5):
    url, token = _validate_connection(url, token)
    req = urllib.request.Request(
        url, data=json.dumps(args, ensure_ascii=False, separators=(",", ":")).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        raise MaintenanceError(f"Upstash HTTP {exc.code}. Periksa izin token dan URL.") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise MaintenanceError("Koneksi Upstash gagal atau timeout.") from None
    except (ValueError, UnicodeDecodeError):
        raise MaintenanceError("Respons Upstash tidak valid.") from None
    if not isinstance(body, dict) or "error" in body or "result" not in body:
        raise MaintenanceError("Upstash menolak perintah atau respons tidak valid.")
    return body["result"]


def _phase_at(status: MaintenanceStatus, now: float) -> MaintenanceStatus:
    if status.until_ts <= now or status.starts_ts <= 0:
        return replace(status, enabled=False, phase="normal", message="", starts_ts=0.0,
                       since_ts=0.0, until_ts=0.0, warning_seconds=0)
    if now >= status.starts_ts:
        phase = "active"
    elif status.warning_seconds and now >= status.starts_ts - status.warning_seconds:
        phase = "warning"
    else:
        phase = "scheduled"
    return replace(status, phase=phase, enabled=(phase == "active"))


def _decode(raw: object, now_ts: float) -> MaintenanceStatus:
    if raw is None:
        return MaintenanceStatus()
    if not isinstance(raw, str):
        raise MaintenanceError("Data maintenance di Upstash tidak valid.")
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict) or obj.get("enabled") is not True:
            raise ValueError("not enabled")
        start = float(obj.get("starts_ts", obj.get("since_ts", 0)))
        end = float(obj.get("until_ts", 0))
        warning = int(obj.get("warning_seconds", 0))
        if (not math.isfinite(start) or not math.isfinite(end) or not 0 < start < 1e11
                or not start < end < 1e11 or not 0 <= warning <= MAX_WARNING):
            raise ValueError("invalid time")
        msg = str(obj.get("message") or "Pemeliharaan sistem sedang berlangsung.")[:MAX_MESSAGE]
    except (ValueError, TypeError, OverflowError):
        raise MaintenanceError("Data maintenance tidak dapat dibaca.") from None
    status = MaintenanceStatus(message=msg, since_ts=start, starts_ts=start, until_ts=end,
                               warning_seconds=warning)
    return _phase_at(status, now_ts)


def read_status(url: str, token: str, app_id: str = "timestamp-pyx", *,
                force: bool = False, at_time: float | None = None) -> MaintenanceStatus:
    """Per-process single-flight poll; shared by all sessions in same worker.

    Brief outages retain a previously observed active/scheduled state until its
    planned expiry. First-ever errors fail open (not suitable for security ACL).
    """
    now = float(time.time() if at_time is None else at_time)
    key = maintenance_key(app_id)
    cache_key = (str(url).rstrip("/"), key)
    moment = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(cache_key)
        if cached and not force and cached[0] > moment:
            return _phase_at(cached[1], now)
        try:
            new = _decode(_command(url, token, ["GET", key]), now)
        except MaintenanceError as exc:
            prior = cached[1] if cached else MaintenanceStatus()
            # Retain last known planned state if still not expired.
            new = replace(_phase_at(prior, now), available=False, detail=str(exc))
        _CACHE[cache_key] = (moment + (CACHE_SECONDS if new.available else ERROR_CACHE_SECONDS), new)
        if len(_CACHE) > 32:
            _CACHE.pop(next(iter(_CACHE)))
        return _phase_at(new, now)


def set_status(url: str, token: str, app_id: str, *, enabled: bool,
               message: str = "", duration_seconds: int = 3600, at_time: float | None = None,
               start_ts: float | None = None, warning_seconds: int = 0) -> None:
    """Immediate/scheduled maintenance, time-based activation, TTL restore.

    Cancelling is DEL. Redis does not require an always-on scheduler/worker.
    """
    key = maintenance_key(app_id)
    now = float(time.time() if at_time is None else at_time)
    if enabled:
        try:
            duration = int(duration_seconds)
            warning = int(warning_seconds)
            start = now if start_ts is None else float(start_ts)
        except (ValueError, TypeError, OverflowError):
            raise MaintenanceError("Parameter jadwal tidak valid.") from None
        if not (MIN_DURATION <= duration <= MAX_DURATION):
            raise MaintenanceError("Durasi harus antara 5 menit dan 24 jam.")
        if not math.isfinite(start) or start < now - 5 or start > now + MAX_SCHEDULE_AHEAD:
            raise MaintenanceError("Waktu mulai harus sekarang hingga 7 hari ke depan.")
        if not (0 <= warning <= MAX_WARNING):
            raise MaintenanceError("Peringatan maksimum 60 menit.")
        if start <= now:
            start = now
            warning = 0
        cleaned = " ".join(str(message or "").split())[:MAX_MESSAGE]
        if not cleaned:
            cleaned = "Sistem sedang dalam pemeliharaan. Silakan coba kembali nanti."
        end = start + duration
        ttl = duration if start == now else math.ceil(end - now) + 2  # TTL auto-restore
        data = {"enabled": True, "starts_ts": int(start), "since_ts": int(start),
                "until_ts": int(end), "warning_seconds": warning, "message": cleaned}
        result = _command(url, token, ["SET", key, json.dumps(data, ensure_ascii=False, separators=(",", ":")), "EX", ttl])
        if result != "OK":
            raise MaintenanceError("Upstash tidak mengonfirmasi pengaturan maintenance.")
    else:
        result = _command(url, token, ["DEL", key])
        if isinstance(result, bool) or not isinstance(result, int) or result < 0:
            raise MaintenanceError("Upstash tidak mengonfirmasi pembatalan maintenance.")
    with _LOCK:
        _CACHE.pop((str(url).rstrip("/"), key), None)


def append_audit(url: str, token: str, app_id: str, *, action: str,
                 at_time: float | None = None) -> None:
    """Bounded anonymous action history; only called after confirmed admin write."""
    if action not in {"activate", "schedule", "cancel"}:
        raise MaintenanceError("Aksi audit tidak valid.")
    key = maintenance_audit_key(app_id)
    payload = json.dumps({"ts": int(time.time() if at_time is None else at_time),
                          "action": action}, separators=(",", ":"))
    _command(url, token, ["LPUSH", key, payload])
    _command(url, token, ["LTRIM", key, 0, 49])


def read_audit(url: str, token: str, app_id: str) -> list[dict]:
    records = _command(url, token, ["LRANGE", maintenance_audit_key(app_id), 0, 49])
    if not isinstance(records, list):
        raise MaintenanceError("Riwayat tindakan tidak valid.")
    parsed = []
    for raw in records:
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict) and obj.get("action") in {"activate", "schedule", "cancel"}:
                parsed.append({"ts": int(obj["ts"]), "action": obj["action"]})
        except (TypeError, ValueError, OverflowError):
            continue
    return parsed


__all__ = ["MaintenanceError", "MaintenanceStatus", "read_status", "set_status", "maintenance_key",
           "validate_namespace", "append_audit", "read_audit", "_decode"]
