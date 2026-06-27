"""Tests for the ComfyUI prompt-graph parser."""

from __future__ import annotations

import json

from ogallery.graph_parser import parse_prompt_graph

SAMPLE_GRAPH = {
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
            "negative": ["7", 0],
        },
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "a cute cat sitting on a windowsill"},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "blurry, lowres, watermark"},
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
    },
}


def test_parses_positive_negative_and_params():
    result = parse_prompt_graph(SAMPLE_GRAPH)

    assert result["positive"] == "a cute cat sitting on a windowsill"
    assert result["negative"] == "blurry, lowres, watermark"

    params = result["params"]
    assert params["seed"] == 1234567890
    assert params["steps"] == 20
    assert params["cfg"] == 7.5
    assert params["sampler_name"] == "dpmpp_2m"
    assert params["scheduler"] == "karras"
    assert params["model"] == "v1-5-pruned-emaonly.safetensors"
    # Raw JSON is preserved for the UI's "raw" panel.
    assert json.loads(result["raw_prompt"]) == SAMPLE_GRAPH
    assert result["raw_workflow"] is None


def test_workflow_is_preserved():
    workflow = {"last_node_id": "7", "last_link_id": 5}
    result = parse_prompt_graph(SAMPLE_GRAPH, workflow)
    assert json.loads(result["raw_workflow"]) == workflow


def test_sampler_advanced_supported():
    graph = {
        "1": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "seed": 42,
                "steps": 30,
                "cfg": 8.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 0.6,
                "positive": ["2", 0],
                "negative": ["3", 0],
            },
        },
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "p"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "n"}},
    }
    result = parse_prompt_graph(graph)
    assert result["positive"] == "p"
    assert result["negative"] == "n"
    assert result["params"]["steps"] == 30
    assert result["params"]["denoise"] == 0.6


def test_no_sampler_heuristic_fallback():
    """When no sampler is present, positive/negative are guessed from encoders."""

    graph = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "a sunny day"}},
        "2": {
            "class_type": "CLIPTextEncode",
            "_meta": {"title": "Negative"},
            "inputs": {"text": "rain"},
        },
    }
    result = parse_prompt_graph(graph)
    assert "sunny" in result["positive"]
    assert "rain" in result["negative"]


def test_chained_conditioning_text_links():
    """A CLIPTextEncode whose ``text`` is itself a link (e.g. to a String node)."""

    graph = {
        "1": {
            "class_type": "KSampler",
            "inputs": {
                "seed": 1, "steps": 10, "cfg": 5.0,
                "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
                "positive": ["2", 0], "negative": ["4", 0],
            },
        },
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ["3", 0]}},
        "3": {"class_type": "ShowText|pysssss", "inputs": {"text": "resolved via chain"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
    }
    result = parse_prompt_graph(graph)
    assert result["positive"] == "resolved via chain"


def test_empty_graph_returns_empty():
    result = parse_prompt_graph({})
    assert result["positive"] == ""
    assert result["negative"] == ""
    assert result["params"] == {}


def test_non_dict_prompt_is_safe():
    result = parse_prompt_graph("not a graph")  # type: ignore[arg-type]
    assert result["positive"] == ""
    assert result["raw_prompt"] == json.dumps("not a graph")
