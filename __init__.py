"""ComfyUI Output Gallery.

A gallery/viewer for generated images in ComfyUI's output directory.
Shows each image with its positive/negative prompt, resolution and generation
parameters, backed by a SQLite index with full-text search, tags and favorites.
"""

from __future__ import annotations

import logging

try:
    from .ogallery.server import add_routes
except ImportError:  # imported as a top-level module (e.g. under pytest)
    from ogallery.server import add_routes

_LOGGER = logging.getLogger(__name__)

# This extension does not register any custom nodes; it only adds a web UI and
# backend routes. NODE_CLASS_MAPPINGS is kept empty so ComfyUI loads us as a
# custom node directory (the only entry point ComfyUI scans).
NODE_CLASS_MAPPINGS: dict = {}

# ComfyUI auto-imports every JS/CSS file under this directory as an ES module.
WEB_DIRECTORY = "./web/comfyui"

__all__ = ["NODE_CLASS_MAPPINGS", "WEB_DIRECTORY", "add_routes"]

# Register backend routes at import time (ComfyUI imports this module once).
# Wrapped defensively so the module remains importable outside the ComfyUI
# runtime (e.g. under pytest), where ``server``/``folder_paths`` are stubbed or
# the aiohttp app is unavailable.
try:
    add_routes()
except Exception as exc:  # pragma: no cover - ComfyUI-only path
    _LOGGER.debug("add_routes skipped: %s", exc)
