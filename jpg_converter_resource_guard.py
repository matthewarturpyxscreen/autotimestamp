"""Backward-compatible JPG admission API, shared with both timestamp batches.

All heavy jobs on the same Streamlit worker use a single process-local
semaphore, preventing simultaneous expensive allocations.
"""
from __future__ import annotations
from contextlib import contextmanager
from typing import Iterator
from pyx_image_job_guard import configured_limit, image_job_slot, ImageServerBusy


class ConverterBusyError(RuntimeError):
    """Another image job already occupies the available server permits."""


@contextmanager
def converter_slot() -> Iterator[None]:
    try:
        with image_job_slot():
            yield
    except ImageServerBusy as exc:
        raise ConverterBusyError(str(exc)) from exc
