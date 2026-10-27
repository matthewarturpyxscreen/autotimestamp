"""Process-local admission control for memory-heavy JPG conversions.

Separate from OCR, the timestamp renderer, Batch Manual and Batch NPSN.
Only a permit counter is global: uploaded images / results are NEVER shared.
If the process restarts, all permits disappear with the process.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from threading import BoundedSemaphore
from typing import Iterator


class ConverterBusyError(RuntimeError):
    """Another heavy JPG conversion already occupies all local permits."""


def configured_limit() -> int:
    """Default conservatively to one CPU/RAM-heavy conversion per process.

    Optional environment override, capped to 3 because Streamlit Community
    Cloud generally has limited memory and simultaneous large documents are
    expensive. Invalid values do not prevent the app from launching.
    """
    try:
        return max(1, min(3, int(os.environ.get('PYX_MAX_CONCURRENT_JPG_JOBS', '1'))))
    except (TypeError, ValueError):
        return 1


_MAX_CONCURRENT = configured_limit()
_SEMAPHORE = BoundedSemaphore(value=_MAX_CONCURRENT)


@contextmanager
def converter_slot() -> Iterator[None]:
    """Fail fast instead of starting multiple 400MB jobs simultaneously.

    The `finally` is essential: both normal completion and image decoder
    failures must release the slot. No uploaded files or user state are held.
    """
    if not _SEMAPHORE.acquire(blocking=False):
        raise ConverterBusyError('Konversi JPG lain masih berjalan di server. Silakan coba kembali setelah proses tersebut selesai.')
    try:
        yield
    finally:
        _SEMAPHORE.release()
