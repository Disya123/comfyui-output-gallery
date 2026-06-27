"""Central configuration: paths to ComfyUI folders, the data dir, templates/static."""

from __future__ import annotations

import logging
import os
from typing import Optional

from .settings_paths import get_data_dir, get_db_path, get_extension_root, get_thumbs_dir

_LOGGER = logging.getLogger(__name__)

# Media extensions we index.
SUPPORTED_MEDIA_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".avif")

# Static URL mounts.
GALLERY_STATIC_URL = "/gallery_static"
GALLERY_ASSETS_URL = "/gallery_assets"  # served from the extension's static/ dir
THUMBS_STATIC_URL = "/gallery_thumbs"

# Max directory scan depth below the output root (0 = unlimited).
DEFAULT_MAX_DEPTH = 0


def _import_folder_paths():
    """Import ComfyUI's ``folder_paths`` module, falling back to None."""

    try:
        import folder_paths  # type: ignore
        return folder_paths
    except Exception:  # pragma: no cover - only fails outside ComfyUI runtime
        _LOGGER.debug("folder_paths not importable; running outside ComfyUI?")
        return None


def get_output_directory() -> str:
    """Return ComfyUI's output directory."""

    fp = _import_folder_paths()
    if fp is not None:
        try:
            return fp.get_output_directory()
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("folder_paths.get_output_directory() failed: %s", exc)
    # Last-resort fallback for tests / standalone runs.
    return os.path.abspath("output")


def get_templates_dir() -> str:
    return os.path.join(get_extension_root(), "templates")


def get_static_dir() -> str:
    return os.path.join(get_extension_root(), "static")
