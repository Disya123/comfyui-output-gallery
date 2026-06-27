"""Resolve the data/settings directory for the Output Gallery.

Mirrors the LoRA Manager approach: a ``settings.json`` in the extension root
with ``"use_portable_settings": true`` forces portable mode (data lives next
to the extension); otherwise we use the platform user-config directory.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from platformdirs import user_config_dir

APP_NAME = "ComfyUI-Output-Gallery"
_LOGGER = logging.getLogger(__name__)


def get_extension_root() -> str:
    """Return the extension's root directory (parent of ``py``)."""

    # py/settings_paths.py -> py -> <root>
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _portable_settings_path() -> str:
    return os.path.join(get_extension_root(), "settings.json")


def _should_use_portable_settings(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("Could not read portable-mode flag from %s: %s", path, exc)
        return False
    if not isinstance(payload, dict):
        return False
    flag = payload.get("use_portable_settings")
    return isinstance(flag, bool) and flag


def get_data_dir(create: bool = True) -> str:
    """Return the directory used to store the SQLite index, thumbnails, etc."""

    legacy_path = _portable_settings_path()
    if _should_use_portable_settings(legacy_path):
        data_dir = os.path.join(get_extension_root(), "data")
    else:
        data_dir = user_config_dir(APP_NAME, appauthor=False)

    if create and data_dir:
        os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_thumbs_dir(create: bool = True) -> str:
    thumbs = os.path.join(get_data_dir(create=create), "thumbs")
    if create:
        os.makedirs(thumbs, exist_ok=True)
    return thumbs


def get_db_path(create_dir: bool = True) -> str:
    return os.path.join(get_data_dir(create=create_dir), "gallery.sqlite")
