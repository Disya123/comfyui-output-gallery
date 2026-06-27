"""Integration tests for the indexer and metadata extractor.

These write real PNG files with embedded ``prompt`` / ``parameters`` text
chunks and verify the indexer builds a correct SQLite index from them.

The ``fake_output_dir`` / ``ext_root`` fixtures (see conftest.py) monkeypatch
the live ``settings_paths`` / ``folder_paths`` attributes and reset the cached
DB connection, so each test runs against a fresh tmp output dir and database.
We import the gallery modules at module scope; their functions resolve the
patched paths at call time.
"""

from __future__ import annotations

import json
import os
import time

from ogallery import config, db, indexer, metadata_extractor as me


def test_comfyui_png_extracts_full_graph(comfy_graph_png):
    meta = me.extract(str(comfy_graph_png))
    assert meta["width"] == 768
    assert meta["height"] == 512
    assert "cute cat" in meta["positive"]
    assert "blurry" in meta["negative"]
    assert meta["params"]["steps"] == 20
    assert meta["params"]["model"] == "v1-5-pruned-emaonly.safetensors"
    assert json.loads(meta["raw_prompt"])["3"]["class_type"] == "KSampler"


def test_a1111_parameters_fallback(a1111_png):
    meta = me.extract(str(a1111_png))
    assert "masterpiece" in meta["positive"]
    assert "lowres" in meta["negative"]
    params = meta["params"]
    assert params.get("Steps") == "25"
    assert params.get("Seed") == "987654"
    assert params.get("width") == 768
    assert params.get("height") == 512


def test_scan_once_indexes_all_files(comfy_graph_png, a1111_png):
    stats = indexer.scan_once()
    assert stats["added"] == 2
    assert stats["errors"] == 0

    result = db.query_images(page=1, limit=10)
    assert result["total"] == 2
    filenames = {i["filename"] for i in result["items"]}
    assert any("ComfyUI_00001_" in n for n in filenames)
    assert any("a1111" in n for n in filenames)


def test_search_finds_image_by_positive_prompt(comfy_graph_png, a1111_png):
    indexer.scan_once()

    result = db.query_images(query="cute cat", page=1, limit=10)
    assert result["total"] == 1
    assert "cat" in result["items"][0]["positive"]


def test_reindex_skips_unchanged_files(comfy_graph_png):
    first = indexer.scan_once()
    assert first["added"] == 1

    # Second scan should find nothing new (mtime unchanged).
    second = indexer.scan_once()
    assert second["added"] == 0
    assert second["updated"] == 0


def test_reindex_picks_up_mtime_change(comfy_graph_png):
    indexer.scan_once()

    new_time = time.time() + 1000
    os.utime(str(comfy_graph_png), (new_time, new_time))

    second = indexer.scan_once()
    assert second["updated"] == 1


def test_pruning_removes_deleted_files(comfy_graph_png):
    indexer.scan_once()
    assert db.get_stats()["total_images"] == 1

    os.remove(str(comfy_graph_png))
    second = indexer.scan_once()
    assert second["pruned"] == 1
    assert db.get_stats()["total_images"] == 0


def test_subdirectory_images_are_indexed(fake_output_dir):
    sub = fake_output_dir / "sessionA"
    sub.mkdir()
    from PIL import Image

    Image.new("RGB", (128, 128), (255, 255, 255)).save(
        str(sub / "nested.png"), format="PNG"
    )

    stats = indexer.scan_once()
    assert stats["added"] == 1
    result = db.query_images(page=1, limit=10)
    assert result["items"][0]["filename"].replace("\\", "/").startswith("sessionA/")
