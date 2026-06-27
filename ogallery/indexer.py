"""Incrementally scan ComfyUI's output directory and refresh the SQLite index.

A scan is cheap when nothing changed: for every file we compare ``os.stat``
mtime against the cached value and skip extraction when they match. Files that
were deleted from disk are pruned from the index.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import concurrent.futures
from typing import Iterable, Optional

from . import config, db
from .thumbnails import generate_background
from .metadata_extractor import extract
from .settings_paths import get_data_dir

_LOGGER = logging.getLogger(__name__)

_scan_lock = threading.Lock()
_scan_running = False
_last_scan = 0.0

_thumb_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=3, thread_name_prefix="ogallery_thumbs"
)

def shutdown() -> None:
    """Cleanly shut down the background thumbnail generator."""
    _thumb_executor.shutdown(wait=False)


def scan_once(max_depth: Optional[int] = None) -> dict:
    """Run one incremental scan. Returns a small stats dict."""

    global _scan_running, _last_scan

    if not _scan_lock.acquire(blocking=False):
        _LOGGER.debug("scan_once already running; skipping")
        return {"skipped": True}
    try:
        _scan_running = True
        return _scan_impl(max_depth)
    finally:
        _last_scan = time.time()
        _scan_running = False
        _scan_lock.release()


def is_running() -> bool:
    return _scan_running


def last_scan_time() -> float:
    return _last_scan


# --------------------------------------------------------------------------- #
# Implementation
# --------------------------------------------------------------------------- #


def _scan_impl(max_depth: Optional[int]) -> dict:
    output_dir = config.get_output_directory()
    if not os.path.isdir(output_dir):
        _LOGGER.warning("Output directory does not exist: %s", output_dir)
        return {"scanned": 0, "added": 0, "updated": 0, "pruned": 0}

    if max_depth is None:
        max_depth = config.DEFAULT_MAX_DEPTH

    supported = config.SUPPORTED_MEDIA_EXTENSIONS
    seen: set[str] = set()
    added = updated = errors = 0

    for rel_path in _walk(output_dir, supported, max_depth):
        # Store paths with forward slashes for URL-safety across platforms.
        filename = rel_path.replace(os.sep, "/")
        seen.add(filename)
        abs_path = os.path.join(output_dir, rel_path)

        try:
            stat = os.stat(abs_path)
        except OSError as exc:
            _LOGGER.debug("stat failed for %s: %s", abs_path, exc)
            errors += 1
            continue

        cached_mtime = db.get_image_mtime(filename)
        if cached_mtime is not None and abs(cached_mtime - stat.st_mtime) < 1e-6:
            continue

        try:
            meta = extract(abs_path)
        except Exception as exc:  # pragma: no cover - defensive
            _LOGGER.warning("extract failed for %s: %s", abs_path, exc)
            errors += 1
            continue

        record = {
            "filename": filename,
            "rel_path": rel_path,
            "mtime": float(stat.st_mtime),
            "size_bytes": int(stat.st_size),
            "width": meta["width"],
            "height": meta["height"],
            "positive": meta["positive"],
            "negative": meta["negative"],
            "params": meta["params"],
            "raw_prompt": meta["raw_prompt"],
            "raw_workflow": meta["raw_workflow"],
            "indexed_at": time.time(),
        }
        db.upsert_image(record)
        
        # Dispatch background thumbnail generation
        _thumb_executor.submit(generate_background, filename)

        if cached_mtime is None:
            added += 1
        else:
            updated += 1

    pruned = _prune_missing(seen)
    _LOGGER.info(
        "Gallery scan complete: %d files, +%d added, ~%d updated, -%d pruned, %d errors",
        len(seen), added, updated, pruned, errors,
    )
    return {
        "scanned": len(seen),
        "added": added,
        "updated": updated,
        "pruned": pruned,
        "errors": errors,
    }


def _walk(root: str, extensions: Iterable[str], max_depth: int) -> Iterable[str]:
    exts = tuple(e.lower() for e in extensions)
    stack = [(root, "", 0)]  # (dir, rel_prefix, depth)
    while stack:
        current, prefix, depth = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError as exc:
            _LOGGER.debug("scandir failed for %s: %s", current, exc)
            continue
        for entry in entries:
            name = entry.name
            if name.startswith("."):
                continue
            rel = os.path.join(prefix, name) if prefix else name
            try:
                if entry.is_dir(follow_symlinks=False):
                    if max_depth and depth + 1 > max_depth:
                        continue
                    stack.append((entry.path, rel, depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    if name.lower().endswith(exts):
                        yield rel
            except OSError:
                continue


def _prune_missing(seen: set) -> int:
    conn = db.get_conn()
    rows = conn.execute("SELECT filename FROM images").fetchall()
    missing = [r["filename"] for r in rows if r["filename"] not in seen]
    for filename in missing:
        db.delete_image(filename)
    return len(missing)
