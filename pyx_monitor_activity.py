"""Privacy-minimal, process-local AutoTimestamp usage telemetry (v1.4).

Never stores photos, OCR, geolocation, names, account IDs or browser IPs.
Session IDs are random and kept in this Python process only; Redis gets
aggregated counters embedded in the existing once-a-minute metrics sample.
"""
from __future__ import annotations

from collections import Counter
from threading import RLock
import time

_LOCK = RLock()
_ACTIVE_WINDOW_S = 180  # active = heartbeat within past three minutes
_RETAIN_WINDOW_S = 900  # expire abandoned browser sessions after 15 minutes
_MAX_SESSION_RECORDS = 3000
_STARTED_AT = int(time.time())
_SESSIONS: dict[str, tuple[float, str]] = {}
_MENU_ENTRIES: Counter[str] = Counter()
_EVENTS: Counter[str] = Counter()
_SESSIONS_SEEN = 0
_LAST_PRUNE_AT = float("-inf")

VALID_MENUS = ("satu_foto", "batch_manual", "batch_npsn", "jpg_converter")
VALID_EVENTS = ("ocr_satu_foto", "ocr_batch_manual", "generate_satu_foto",
                "generate_batch_manual", "generate_batch_npsn", "konversi_jpg")


def _prune(now: float) -> None:
    global _LAST_PRUNE_AT
    _LAST_PRUNE_AT = now
    old = [sid for sid, (seen, _) in _SESSIONS.items() if now - seen > _RETAIN_WINDOW_S]
    for sid in old:
        _SESSIONS.pop(sid, None)
    # Cap memory even if thousands of short-lived sessions are created.
    if len(_SESSIONS) >= _MAX_SESSION_RECORDS:
        for sid, _ in sorted(_SESSIONS.items(), key=lambda item: item[1][0])[:len(_SESSIONS) - _MAX_SESSION_RECORDS + 1]:
            _SESSIONS.pop(sid, None)


def mark_session(session_id: str, menu: str, *, at_time: float | None = None) -> None:
    """Touch a random browser-session ID and count menu transitions once."""
    global _SESSIONS_SEEN
    if not isinstance(session_id, str) or len(session_id) != 32 or not session_id.isascii() or not all(c in '0123456789abcdef' for c in session_id):
        return
    if menu not in VALID_MENUS:
        return
    now = float(time.time() if at_time is None else at_time)
    with _LOCK:
        # Amortize cleanup: don't scan thousands of active sessions for every
        # browser heartbeat. Metrics snapshots still prune each minute.
        if now - _LAST_PRUNE_AT >= 30 or len(_SESSIONS) >= _MAX_SESSION_RECORDS:
            _prune(now)
        previous = _SESSIONS.get(session_id)
        if previous is None:
            _SESSIONS_SEEN += 1
        if previous is None or previous[1] != menu:
            _MENU_ENTRIES[menu] += 1
        _SESSIONS[session_id] = (now, menu)


def record_event(name: str, count: int = 1) -> None:
    """Record successful operations only, as process-wide aggregate counters."""
    if name not in VALID_EVENTS or not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 10_000:
        return
    with _LOCK:
        _EVENTS[name] += count


def snapshot_activity(*, at_time: float | None = None) -> dict:
    """Return bounded, anonymous aggregates safe to persist in a metric sample."""
    now = float(time.time() if at_time is None else at_time)
    with _LOCK:
        _prune(now)
        active = Counter(menu for seen, menu in _SESSIONS.values()
                         if 0 <= now - seen <= _ACTIVE_WINDOW_S)
        return {
            "version": 1,
            "boot": _STARTED_AT,
            "window_seconds": _ACTIVE_WINDOW_S,
            "active_sessions": sum(active.values()),
            "active_by_menu": {key: active[key] for key in VALID_MENUS},
            "sessions_seen": _SESSIONS_SEEN,
            "menu_entries": {key: _MENU_ENTRIES[key] for key in VALID_MENUS},
            "events": {key: _EVENTS[key] for key in VALID_EVENTS},
        }


__all__ = ["mark_session", "record_event", "snapshot_activity", "VALID_MENUS", "VALID_EVENTS"]
