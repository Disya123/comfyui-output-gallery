"""Extract prompt/workflow/resolution metadata from an image file on disk.

ComfyUI's ``SaveImage`` node stores the executed prompt graph and workflow as
PNG text chunks named ``prompt`` and ``workflow`` (JSON strings). For JPEG/WebP
the metadata is written into the EXIF ``UserComment``. We read both and fall
back to A1111-style ``parameters`` text when present.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from .graph_parser import parse_prompt_graph

_LOGGER = logging.getLogger(__name__)


def extract(path: str) -> dict:
    """Return an image metadata record suitable for ``db.upsert_image``.

    Keys: ``width, height, positive, negative, params, raw_prompt,
    raw_workflow``. Never raises; on failure returns a minimal record.
    """

    record: dict[str, Any] = {
        "width": 0,
        "height": 0,
        "positive": "",
        "negative": "",
        "params": {},
        "raw_prompt": None,
        "raw_workflow": None,
    }

    try:
        from PIL import Image  # type: ignore
    except ImportError:  # pragma: no cover
        _LOGGER.error("Pillow is required to extract image metadata")
        return record

    try:
        with Image.open(path) as img:
            record["width"], record["height"] = img.size
            info = dict(getattr(img, "info", {}) or {})
    except Exception as exc:
        _LOGGER.warning("Could not open image %s: %s", path, exc)
        return record

    structured = _load_structured(path, info)

    prompt_raw = structured.get("prompt")
    workflow_raw = structured.get("workflow")
    parameters_text = structured.get("parameters")

    if prompt_raw:
        try:
            prompt_json = json.loads(prompt_raw)
            parsed = (
                parse_prompt_graph(prompt_json, _maybe_json(workflow_raw))
                if isinstance(prompt_json, dict)
                else _empty_parsed(prompt_raw, workflow_raw)
            )
            record.update(parsed)
            return record
        except (json.JSONDecodeError, TypeError) as exc:
            _LOGGER.debug("prompt chunk not JSON for %s: %s", path, exc)

    # A1111-style parameters text (or whatever string we have).
    text = parameters_text or prompt_raw or ""
    positive, negative, params = _parse_a1111_parameters(text)
    record["positive"] = positive
    record["negative"] = negative
    record["params"] = params
    record["raw_prompt"] = prompt_raw or parameters_text
    record["raw_workflow"] = workflow_raw
    return record


# --------------------------------------------------------------------------- #
# Low-level loaders
# --------------------------------------------------------------------------- #


def _load_structured(path: str, info: dict) -> dict:
    """Return a dict with any of ``parameters``, ``prompt``, ``workflow``."""

    structured = {}
    for key in ("parameters", "prompt", "workflow"):
        value = info.get(key)
        if isinstance(value, bytes):
            try:
                value = value.decode("utf-8", errors="replace")
            except Exception:
                value = None
        if isinstance(value, str) and value:
            structured[key] = value

    # JPEG/WebP store metadata in EXIF UserComment; Pillow surfaces it via
    # ``info`` on some versions but not all, so probe piexif as a fallback.
    if not structured and path.lower().endswith((".jpg", ".jpeg", ".webp", ".tiff")):
        comment = _read_exif_user_comment(path)
        if comment:
            structured.setdefault("parameters", comment)
            # ComfyUI sometimes embeds JSON in the comment.
            if comment.lstrip().startswith("{"):
                structured.setdefault("prompt", comment)

    return structured


def _read_exif_user_comment(path: str) -> Optional[str]:
    try:
        import piexif  # type: ignore
    except ImportError:
        return None
    try:
        piexif.load(path)
    except Exception:
        return None
    try:
        exif = piexif.load(path)
    except Exception:
        return None
    user_comment = (exif or {}).get("Exif", {}).get(piexif.ExifIFD.UserComment)
    if not user_comment:
        return None
    return _decode_user_comment(user_comment)


def _decode_user_comment(value) -> Optional[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        # ComfyUI writes b"UNICODE\0" + utf-16be payload.
        if value.startswith(b"UNICODE\x00"):
            try:
                return value[8:].decode("utf-16-be", errors="replace")
            except Exception:
                pass
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return None
    return None


# --------------------------------------------------------------------------- #
# A1111-style parameters parser (fallback)
# --------------------------------------------------------------------------- #


def _parse_a1111_parameters(text: str) -> tuple:
    """Parse ``"prompt\nNegative prompt: ...\nSteps: ..., Size: ..., ..."``."""

    positive, negative, params = "", "", {}
    if not text:
        return positive, negative, params

    try:
        text = text.strip()
    except Exception:
        return positive, negative, params

    if "Negative prompt:" in text:
        head, _, tail = text.partition("Negative prompt:")
        positive = head.strip()
        # tail may itself contain newlines before the generation params.
        neg, _, params_line = tail.partition("\n")
        negative = neg.strip()
        params = _parse_param_line(params_line)
    else:
        # The last line after the final newline holds the key=value params.
        lines = text.split("\n")
        if len(lines) > 1 and "=" in lines[-1] or (len(lines) > 1 and ":" in lines[-1]):
            positive = "\n".join(lines[:-1]).strip()
            params = _parse_param_line(lines[-1])
        else:
            positive = text

    size = params.get("Size")
    if isinstance(size, str) and "x" in size:
        try:
            w, h = size.lower().split("x")[0:2]
            params["width"] = int(float(w))
            params["height"] = int(float(h))
        except (ValueError, IndexError):
            pass

    return positive, negative, params


def _parse_param_line(line: str) -> dict:
    params: dict[str, Any] = {}
    for chunk in line.split(","):
        chunk = chunk.strip()
        if "=" not in chunk and ":" not in chunk:
            continue
        sep = "=" if "=" in chunk else ":"
        key, _, value = chunk.partition(sep)
        key = key.strip()
        value = value.strip()
        if key:
            params[key] = value
    return params


def _maybe_json(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _empty_parsed(prompt_raw, workflow_raw) -> dict:
    return {
        "positive": "",
        "negative": "",
        "params": {},
        "raw_prompt": prompt_raw,
        "raw_workflow": workflow_raw,
    }
