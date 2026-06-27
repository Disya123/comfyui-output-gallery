"""Gallery API routes.

Registered with ComfyUI's aiohttp app by ``py.server.add_routes``. Endpoints
live under ``/api/gallery``.

NOTE: ``register_api_routes`` is imported by ``server.py`` at registration
time; it must be import-safe even before the DB/indexer modules exist (they
are imported lazily inside handlers).
"""

from __future__ import annotations

import logging
from typing import Any

from .. import config

_LOGGER = logging.getLogger(__name__)

API_PREFIX = "/api/gallery"


def register_api_routes(app) -> None:
    """Register all ``/api/gallery/*`` routes on the given aiohttp app."""

    from aiohttp import web

    app.router.add_get(f"{API_PREFIX}/images", _handle_images)
    app.router.add_get(f"{API_PREFIX}/image", _handle_image)
    app.router.add_post(f"{API_PREFIX}/favorite", _handle_favorite)
    app.router.add_get(f"{API_PREFIX}/tags", _handle_tags)
    app.router.add_post(f"{API_PREFIX}/tag", _handle_add_tag)
    app.router.add_post(f"{API_PREFIX}/untag", _handle_remove_tag)
    app.router.add_post(f"{API_PREFIX}/reindex", _handle_reindex)
    app.router.add_get(f"{API_PREFIX}/stats", _handle_stats)
    app.router.add_get(f"{API_PREFIX}/thumb", _handle_thumb)


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #


def _json(data: Any, status: int = 200):
    from aiohttp import web

    return web.json_response(data, status=status)


def _query_int(request, name: str, default: int) -> int:
    raw = request.query.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


async def _handle_images(request):
    from ..db import query_images

    params = {
        "query": request.query.get("query") or "",
        "tag": request.query.get("tag") or "",
        "favorite": request.query.get("favorite") == "1",
        "min_width": _query_int(request, "min_width", 0),
        "sort": request.query.get("sort") or "date",
        "page": max(1, _query_int(request, "page", 1)),
        "limit": max(1, min(200, _query_int(request, "limit", 48))),
    }
    result = query_images(**params)
    return _json(result)


async def _handle_image(request):
    from ..db import get_image

    name = request.query.get("name")
    if not name:
        return _json({"success": False, "error": "name required"}, status=400)
    image = get_image(name)
    if image is None:
        return _json({"success": False, "error": "not found"}, status=404)
    return _json({"success": True, "image": image})


async def _handle_favorite(request):
    from ..db import set_favorite

    body = await request.json()
    name = body.get("name")
    favorite = bool(body.get("favorite"))
    if not name:
        return _json({"success": False, "error": "name required"}, status=400)
    set_favorite(name, favorite)
    return _json({"success": True})


async def _handle_tags(request):
    from ..db import list_tags

    return _json({"success": True, "tags": list_tags()})


async def _handle_add_tag(request):
    from ..db import add_tag

    body = await request.json()
    name = body.get("name")
    tag = body.get("tag")
    if not name or not tag:
        return _json({"success": False, "error": "name and tag required"}, status=400)
    add_tag(name, tag)
    return _json({"success": True})


async def _handle_remove_tag(request):
    from ..db import remove_tag

    body = await request.json()
    name = body.get("name")
    tag = body.get("tag")
    if not name or not tag:
        return _json({"success": False, "error": "name and tag required"}, status=400)
    remove_tag(name, tag)
    return _json({"success": True})


async def _handle_reindex(request):
    from ..indexer import scan_once

    scan_once()
    return _json({"success": True})


async def _handle_stats(request):
    from ..db import get_stats

    return _json({"success": True, "stats": get_stats()})


async def _handle_thumb(request):
    """Generate (or serve cached) thumbnail for an image."""

    from aiohttp import web
    from ..thumbnails import get_thumbnail_path

    name = request.query.get("name")
    if not name:
        return _json({"success": False, "error": "name required"}, status=400)
    width = _query_int(request, "w", 320)
    try:
        thumb_url = get_thumbnail_path(name, width)
    except FileNotFoundError:
        return _json({"success": False, "error": "not found"}, status=404)
    raise web.HTTPFound(thumb_url)
