"""On-the-fly thumbnail generation with a disk cache.

Images are served by URL ``/gallery_thumbs/<hash>.jpg`` (a static mount over
the thumbs dir). ``get_thumbnail_path`` generates the file on first request and
returns its public URL.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

from . import config
from .settings_paths import get_thumbs_dir

_LOGGER = logging.getLogger(__name__)

_THUMB_EXT = ".webp"


def get_thumbnail_path(filename: str, width: int = 320) -> str:
    """Generate (if needed) and return the thumbnail's public URL.

    Raises ``FileNotFoundError`` if the source image does not exist.
    """

    output_dir = config.get_output_directory()
    src = os.path.join(output_dir, filename)

    if not os.path.isfile(src):
        raise FileNotFoundError(filename)

    thumbs_dir = get_thumbs_dir(create=True)
    digest = hashlib.sha1(
        f"{filename}|{width}|{int(os.path.getmtime(src))}".encode("utf-8")
    ).hexdigest()
    thumb_name = digest + _THUMB_EXT
    thumb_path = os.path.join(thumbs_dir, thumb_name)

    if not os.path.exists(thumb_path):
        _generate(src, thumb_path, width)

    return f"{config.THUMBS_STATIC_URL}/{thumb_name}"


def _generate(src: str, dest: str, width: int) -> None:
    from PIL import Image  # type: ignore

    try:
        with Image.open(src) as img:
            img.load()
            ratio = width / float(img.width or 1)
            height = max(1, int(img.height * ratio))
            thumb = img.resize((width, height), Image.LANCZOS)
            thumb.save(dest, format="WEBP", quality=80, method=2)
    except Exception as exc:
        _LOGGER.warning("Thumbnail generation failed for %s: %s", src, exc)
        # Fall back to a 1x1 transparent webp so the URL still resolves.
        try:
            Image.new("RGB", (1, 1)).save(dest, format="WEBP")
        except Exception:
            raise
