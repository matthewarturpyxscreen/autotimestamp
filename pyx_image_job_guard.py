"""Bound process-wide concurrency for heavy image work on Streamlit Cloud.

All users share a tiny permit counter, but NEVER share private image files,
metadata, or generated results. This module does not touch image pixels.
"""
from __future__ import annotations
from contextlib import contextmanager
import os
from threading import BoundedSemaphore
from typing import Iterator


class ImageServerBusy(RuntimeError):
    """Image work is already using the available worker capacity."""


def configured_limit() -> int:
    # Keep backward compatibility with the original JPG-specific setting.
    text = os.environ.get('PYX_MAX_CONCURRENT_IMAGE_JOBS',
                          os.environ.get('PYX_MAX_CONCURRENT_JPG_JOBS', '1'))
    try:
        return max(1, min(3, int(text)))
    except (TypeError, ValueError):
        return 1


_MAX_IMAGE_JOBS = configured_limit()
_PERMITS = BoundedSemaphore(_MAX_IMAGE_JOBS)


@contextmanager
def image_job_slot() -> Iterator[None]:
    """Reject overloaded work rather than queueing unbounded image buffers."""
    if not _PERMITS.acquire(blocking=False):
        raise ImageServerBusy(
            'Server sedang memproses gambar dari pengguna lain. '
            'Coba Generate kembali setelah proses sebelumnya selesai.'
        )
    try:
        yield
    finally:
        _PERMITS.release()
