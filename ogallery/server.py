"""Register backend routes and static mounts with ComfyUI's aiohttp server."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from . import config
from .settings_paths import get_thumbs_dir

_LOGGER = logging.getLogger(__name__)

# jinja2 Environment (lazily created so the dependency is only required when
# the gallery page is actually served).
_jinja_env = None


def _get_jinja_env():
    global _jinja_env
    if _jinja_env is None:
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        _jinja_env = Environment(
            loader=FileSystemLoader(config.get_templates_dir()),
            autoescape=select_autoescape(["html", "xml"]),
        )
    return _jinja_env


def _serve_gallery_html(request):  # noqa: ANN001 - aiohttp request
    """Render the gallery SPA shell."""

    from aiohttp import web

    try:
        template = _get_jinja_env().get_template("gallery.html")
        body = template.render(
            assets_url=config.GALLERY_ASSETS_URL,
            gallery_static_url=config.GALLERY_STATIC_URL,
        )
        return web.Response(text=body, content_type="text/html")
    except Exception as exc:  # pragma: no cover - render error path
        _LOGGER.exception("Failed to render gallery page: %s", exc)
        return web.Response(text=f"Gallery render error: {exc}", status=500)


def _get_app():
    """Return ComfyUI's aiohttp application."""

    from server import PromptServer  # type: ignore

    return PromptServer.instance.app


def _add_routes_safe(app, registrar) -> None:
    """Idempotently register a block of routes via a registrar callable."""

    try:
        registrar(app)
    except Exception as exc:  # pragma: no cover - defensive
        _LOGGER.warning("Route registration failed: %s", exc)


def add_routes() -> None:
    """Register all gallery routes with ComfyUI's server.

    Called once from the extension ``__init__`` at import time.
    """

    try:
        app = _get_app()
    except Exception as exc:  # pragma: no cover - happens if ComfyUI not running
        _LOGGER.warning("Could not obtain ComfyUI server app: %s", exc)
        return

    output_dir = config.get_output_directory()
    _LOGGER.info("Output Gallery watching: %s", output_dir)

    # Serve generated images directly (lazy range requests via aiohttp).
    if os.path.isdir(output_dir):
        app.router.add_static(config.GALLERY_STATIC_URL, output_dir, show_index=False)

    # Serve the extension's own static assets (gallery.js / gallery.css).
    static_dir = config.get_static_dir()
    if os.path.isdir(static_dir):
        app.router.add_static(config.GALLERY_ASSETS_URL, static_dir, show_index=False)

    # Serve pre-generated thumbnails from the data dir.
    thumbs_dir = get_thumbs_dir(create=True)
    app.router.add_static(config.THUMBS_STATIC_URL, thumbs_dir, show_index=False)

    # Gallery SPA page.
    app.router.add_get("/gallery", _serve_gallery_html)

    # API routes (registered separately; module may grow).
    from .routes.gallery_routes import register_api_routes

    _add_routes_safe(app, register_api_routes)

    # Build/refresh the index in a background thread once the server starts.
    async def _on_startup(_app) -> None:
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _run_initial_scan)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Initial gallery scan failed: %s", exc)

    async def _on_cleanup(_app) -> None:
        from . import indexer
        try:
            indexer.shutdown()
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Gallery shutdown failed: %s", exc)

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)


def _run_initial_scan() -> None:
    """Run an incremental scan in a background thread."""

    from .indexer import scan_once

    try:
        scan_once()
    except Exception as exc:  # pragma: no cover
        _LOGGER.warning("Gallery scan_once raised: %s", exc)
