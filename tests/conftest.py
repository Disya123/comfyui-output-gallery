"""Pytest bootstrap for the Output Gallery.

The server-side code lives under the ``ogallery`` package. We stub the ComfyUI
runtime modules (``server``, ``folder_paths``, ``nodes``) so the gallery
imports cleanly outside the ComfyUI runtime, and the fixtures redirect the data
dir / output dir to tmp paths.

We deliberately avoid ``importlib.reload`` here: the gallery modules capture
helpers (e.g. ``db`` imports ``get_db_path`` from ``settings_paths``) at import
time, and reloads create *new* module objects that other modules do not see.
Instead we monkeypatch the live module attributes and reset the cached DB
connection so each test opens a fresh tmp database.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _HashableModule(types.ModuleType):
    """A mock module that is hashable so third-party iteration is safe."""

    def __hash__(self):
        return hash(self.__name__)

    def __eq__(self, other):
        if isinstance(other, _HashableModule):
            return self.__name__ == other.__name__
        return NotImplemented


# Stub ComfyUI runtime modules so the gallery imports cleanly outside ComfyUI.
_server_mock = _HashableModule("server")
_server_mock.PromptServer = mock.MagicMock()
sys.modules.setdefault("server", _server_mock)

_folder_paths_mock = _HashableModule("folder_paths")
_folder_paths_mock.get_folder_paths = lambda *_a, **_k: []
_folder_paths_mock.folder_names_and_paths = {}
_folder_paths_mock.get_output_directory = lambda: ""
sys.modules.setdefault("folder_paths", _folder_paths_mock)

_nodes_mock = _HashableModule("nodes")
_nodes_mock.NODE_CLASS_MAPPINGS = {}
sys.modules.setdefault("nodes", _nodes_mock)


@pytest.fixture(autouse=True)
def _reset_db_connection():
    """Drop any cached DB connection before *and* after each test."""

    import ogallery.db as db
    db._conn = None  # noqa: SLF001
    yield
    db._conn = None  # noqa: SLF001


@pytest.fixture()
def ext_root(tmp_path, monkeypatch):
    """Force the gallery's data dir (DB, thumbs) into a tmp extension root."""

    root = tmp_path / "ext"
    (root / "data" / "thumbs").mkdir(parents=True)
    (root / "settings.json").write_text(
        '{"use_portable_settings": true}', encoding="utf-8"
    )

    from ogallery import settings_paths

    monkeypatch.setattr(settings_paths, "get_extension_root", lambda: str(root))
    monkeypatch.setattr(
        settings_paths, "_should_use_portable_settings", lambda _p: True
    )
    return root


@pytest.fixture()
def fake_output_dir(tmp_path, monkeypatch, ext_root):
    """Redirect ``folder_paths.get_output_directory`` to a tmp dir."""

    out = tmp_path / "output"
    out.mkdir()

    fp = sys.modules["folder_paths"]
    monkeypatch.setattr(fp, "get_output_directory", lambda: str(out))
    return out


@pytest.fixture()
def comfy_graph_png(fake_output_dir):
    """A PNG whose ``prompt`` chunk holds a realistic ComfyUI graph."""

    return _write_png(
        fake_output_dir / "ComfyUI_00001_.png", _SAMPLE_GRAPH, chunk="prompt"
    )


@pytest.fixture()
def a1111_png(fake_output_dir):
    """A PNG with an A1111-style ``parameters`` text chunk."""

    text = (
        "masterpiece, best quality, 1girl\n"
        "Negative prompt: lowres, bad anatomy\n"
        "Steps: 25, Sampler: DPM++ 2M, CFG scale: 7, "
        "Seed: 987654, Size: 768x512, Model: anythingv4"
    )
    return _write_png(fake_output_dir / "a1111.png", text, chunk="parameters")


def _write_png(path, payload, chunk="prompt"):
    from PIL import Image, PngImagePlugin
    import io

    meta = PngImagePlugin.PngInfo()
    meta.add_text(chunk, payload)
    img = Image.new("RGB", (768, 512), (40, 60, 90))
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=meta)
    path.write_bytes(buf.getvalue())
    return path


# A minimal but representative ComfyUI prompt graph: a KSampler wired to two
# CLIPTextEncode nodes (positive/negative) plus a checkpoint loader.
_SAMPLE_GRAPH = """{
  "3": {
    "class_type": "KSampler",
    "inputs": {
      "seed": 1234567890,
      "steps": 20,
      "cfg": 7.5,
      "sampler_name": "dpmpp_2m",
      "scheduler": "karras",
      "denoise": 1.0,
      "positive": ["6", 0],
      "negative": ["7", 0]
    }
  },
  "6": {
    "class_type": "CLIPTextEncode",
    "inputs": {"text": "a cute cat sitting on a windowsill, soft light"}
  },
  "7": {
    "class_type": "CLIPTextEncode",
    "inputs": {"text": "blurry, lowres, watermark"}
  },
  "4": {
    "class_type": "CheckpointLoaderSimple",
    "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"}
  }
}"""
