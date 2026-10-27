"""Optional lightweight AutoTimestamp process telemetry agent.

Independent of OCR, rendering, conversion and user/session data. It collects
process resource statistics only and sends them to the configured Redis REST
endpoint. A single daemon thread is started per Python process, and failures
never affect application requests.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

_LOG = logging.getLogger(__name__)
_LOCK = threading.Lock()
_AGENT_THREAD: threading.Thread | None = None
_SAMPLE_INTERVAL_SECONDS = 60
_HISTORY_LIMIT = 1440  # 24 hours at one sample per minute
_TTL_REFRESH_SECONDS = 12 * 3600  # Refresh expiry twice a day, not on every sample


def _setting(name: str) -> str:
    env_val = os.environ.get(name, "")
    if env_val:
        return env_val.strip()
    try:
        import streamlit as st
        value = st.secrets.get(name, "")
        return str(value).strip() if value else ""
    except Exception:
        return ""


def _cgroup_number(name: str) -> int | None:
    for base in (Path("/sys/fs/cgroup"), Path("/sys/fs/cgroup/memory")):
        candidate = base / name
        try:
            raw = candidate.read_text(encoding="ascii").strip()
            if not raw or raw == "max":
                return None
            result = int(raw)
            if 0 < result < 1_000_000_000_000:  # ignore effectively unlimited cgroups
                return result
        except (OSError, ValueError):
            pass
    return None


def _cpu_quota_cores() -> float | None:
    """Best-effort cgroup CPU quota; None means unavailable/unlimited."""
    try:
        value = Path("/sys/fs/cgroup/cpu.max").read_text(encoding="ascii").split()
        if len(value) == 2 and value[0] != "max":
            quota, period = int(value[0]), int(value[1])
            if quota > 0 and period > 0:
                return round(quota / period, 2)
    except (OSError, ValueError):
        pass
    try:
        base = Path("/sys/fs/cgroup/cpu")
        quota = int((base / "cpu.cfs_quota_us").read_text().strip())
        period = int((base / "cpu.cfs_period_us").read_text().strip())
        if quota > 0 and period > 0:
            return round(quota / period, 2)
    except (OSError, ValueError):
        pass
    return None


def _temp_disk_free_mb() -> float | None:
    """Available space on temp mount; not the account-level Cloud disk quota."""
    try:
        return round(shutil.disk_usage(tempfile.gettempdir()).free / 1048576, 1)
    except (OSError, ValueError):
        return None


def collect_process_metrics(process=None, at_time=None) -> dict:
    """Return only resource metrics, never users, filenames or document contents.

    CPU percentage is psutil process CPU consumption with 100%=one logical
    core, so values >100% are possible on multi-core workloads.
    """
    import psutil

    proc = process if process is not None else psutil.Process(os.getpid())
    now = float(at_time if at_time is not None else time.time())
    with proc.oneshot():
        cpu_pct = round(float(proc.cpu_percent(interval=None)), 1)
        rss_mb = round(proc.memory_info().rss / (1024 ** 2), 1)
        threads = int(proc.num_threads())
        started = float(proc.create_time())
    cg_mem_bytes = _cgroup_number("memory.current")
    cg_limit_bytes = _cgroup_number("memory.max")
    if cg_limit_bytes is None:
        cg_limit_bytes = _cgroup_number("memory.limit_in_bytes")
    values = {
        "ts": now,
        "cpu_pct_one_core": cpu_pct,
        "process_ram_mb": rss_mb,
        "threads": threads,
        "process_uptime_s": int(max(0, now - started)),
        "container_ram_mb": round(cg_mem_bytes / (1024 ** 2), 1) if cg_mem_bytes else None,
        "container_limit_mb": round(cg_limit_bytes / (1024 ** 2), 1) if cg_limit_bytes else None,
        "cpu_quota_cores": _cpu_quota_cores(),
        "temp_disk_free_mb": _temp_disk_free_mb(),
    }
    # V1.4: append anonymous activity aggregates to this same telemetry record.
    # No additional Redis commands, no per-event HTTP requests and no user IDs.
    try:
        from pyx_monitor_activity import snapshot_activity
        values["activity"] = snapshot_activity(at_time=now)
    except Exception:
        pass  # monitoring is strictly optional, never breaks main processing
    return values


def _write_sample(url: str, token: str, namespace: str, sample: dict, timeout: float = 4.0, refresh_ttl: bool = True) -> None:
    """Bounded rolling history; no responses sent to the main app UI."""
    key = f"pyx-monitor:{namespace}:history"
    commands = [
        ["LPUSH", key, json.dumps(sample, separators=(",", ":"))],
        ["LTRIM", key, 0, _HISTORY_LIMIT - 1],
    ]
    # Keep auto-cleanup after inactivity, but avoid an EXPIRE command every minute.
    if refresh_ttl:
        commands.append(["EXPIRE", key, 172800])
    data = json.dumps(commands).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/pipeline", data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result, list) or len(result) != len(commands) or any(not isinstance(x, dict) or "error" in x for x in result):
        raise RuntimeError("Storage rejected telemetry commands")


def _agent_loop(url: str, token: str, namespace: str, every: int) -> None:
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        proc.cpu_percent(interval=None)  # prime process CPU measurement
    except Exception:
        _LOG.exception("PYX monitor psutil initialization failed")
        return
    # Use wait rather than sleeping at import: startup is not blocked.
    stop = threading.Event()
    last_ttl_refresh = 0.0
    while not stop.wait(every):
        try:
            metric = collect_process_metrics(process=proc)
            refresh_ttl = time.monotonic() - last_ttl_refresh >= _TTL_REFRESH_SECONDS
            _write_sample(url, token, namespace, metric, refresh_ttl=refresh_ttl)
            if refresh_ttl:
                last_ttl_refresh = time.monotonic()
        except Exception as err:
            # Never alter application behavior if telemetry is unavailable.
            _LOG.warning("PYX monitoring sample skipped: %s", type(err).__name__)


def start_monitoring() -> bool:
    """Safe, idempotent initialization on Streamlit reruns.

    Disabled by default until credentials are set in Streamlit Cloud Secrets.
    """
    global _AGENT_THREAD
    url = _setting("PYX_METRICS_URL")
    token = _setting("PYX_METRICS_WRITE_TOKEN")
    namespace = _setting("PYX_METRICS_APP_ID") or "timestamp-pyx"
    if not url or not token:
        return False
    if not url.startswith("https://"):
        _LOG.warning("PYX monitor requires an HTTPS metrics endpoint")
        return False
    # Keep Redis key names stable and free of characters that could be confusing.
    if not all(c.isalnum() or c in "-_" for c in namespace) or len(namespace) > 60:
        _LOG.warning("Invalid PYX_METRICS_APP_ID")
        return False
    try:
        every = max(30, int(_setting("PYX_METRICS_INTERVAL") or _SAMPLE_INTERVAL_SECONDS))
    except ValueError:
        every = _SAMPLE_INTERVAL_SECONDS
    with _LOCK:
        if _AGENT_THREAD is not None and _AGENT_THREAD.is_alive():
            return True
        _AGENT_THREAD = threading.Thread(
            target=_agent_loop, args=(url, token, namespace, every),
            daemon=True, name="pyx-monitor-telemetry",
        )
        _AGENT_THREAD.start()
    return True


__all__ = ["start_monitoring", "collect_process_metrics"]
