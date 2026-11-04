"""Disk-spooled ZIP results for Batch Manual and Batch NPSN.

The finished image bytes and filenames are unaltered. Only the ZIP
storage/compression path and download adapter differ from previous builds.
"""
from __future__ import annotations
from contextlib import contextmanager
import os
import tempfile
from typing import Iterator

ZIP_RAM_THRESHOLD = 8 * 1024 * 1024


def new_archive():
    """Keep small ZIPs in RAM and spill large batches to OS temporary disk."""
    return tempfile.SpooledTemporaryFile(max_size=ZIP_RAM_THRESHOLD, mode='w+b')


@contextmanager
def download_data(result: dict) -> Iterator[object]:
    """A Streamlit-compatible binary reader; keep original session ZIP alive."""
    handle = result.get('zip_file')
    if handle is None:
        yield result['zip_bytes']  # Old sessions / backward compatibility.
        return
    if handle.closed:
        raise OSError('ZIP sementara sudah ditutup. Silakan Generate ulang.')
    handle.flush()
    # A dup fd is a BufferedReader understood by st.download_button. The
    # session's original tempfile remains open across Streamlit reruns.
    with os.fdopen(os.dup(handle.fileno()), 'rb') as stream:
        stream.seek(0)
        yield stream


def close_result(result: dict | None) -> None:
    """Explicitly dispose old per-session temp files on new Generate/reset."""
    if result:
        handle = result.get('zip_file')
        if handle is not None and not handle.closed:
            handle.close()
