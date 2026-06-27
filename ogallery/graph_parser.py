"""Parse a ComfyUI prompt/workflow graph into readable prompt text + params.

ComfyUI stores the executed prompt graph as JSON in the PNG ``prompt`` text
chunk. The graph is a dict keyed by node id, each value shaped like::

    {
        "class_type": "KSampler",
        "inputs": {
            "seed": 12345,
            "steps": 20,
            "cfg": 7.0,
            "positive": ["6", 0],     # link to node "6", output slot 0
            "negative": ["7", 0],
            ...
        }
    }

Link references are ``[node_id, output_slot]`` lists. We resolve the positive
and negative conditioning links back to ``CLIPTextEncode`` nodes and read their
``text`` widget (which may itself be a link, so we recurse).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

_LOGGER = logging.getLogger(__name__)

# Nodes that sample latent -> they carry positive/negative conditioning links.
SAMPLER_CLASS_TYPES = {
    "KSampler",
    "KSamplerAdvanced",
    "KSampler (Efficient)",
    "SamplerCustom",
    "SamplerCustomAdvanced",
}

# Conditioning nodes that hold the prompt text.
TEXT_ENCODE_CLASS_TYPES = {
    "CLIPTextEncode",
    "CLIPTextEncodeSDXL",
    "CLIPTextEncodeSDXLRefiner",
    "T5TextEncode",
    "Lumina2TextEncode",
    "JoyCaption",
    "ShowText|pysssss",
}

# Nodes that load a model / give us a model name.
MODEL_LOADER_CLASS_TYPES = {
    "CheckpointLoaderSimple",
    "CheckpointLoader",
    "UNETLoader",
    "UnetLoaderGGUF",
    "Load Diffusion Model",
}


def parse_prompt_graph(
    prompt_json: dict, workflow_json: Optional[dict] = None
) -> dict:
    """Return ``{positive, negative, params, raw_prompt, raw_workflow}``."""

    raw_prompt = json.dumps(prompt_json, ensure_ascii=False) if prompt_json else None
    raw_workflow = (
        json.dumps(workflow_json, ensure_ascii=False) if workflow_json else None
    )

    result = {
        "positive": "",
        "negative": "",
        "params": {},
        "raw_prompt": raw_prompt,
        "raw_workflow": raw_workflow,
    }

    if not isinstance(prompt_json, dict):
        return result

    samplers = _nodes_by_class(prompt_json, SAMPLER_CLASS_TYPES)
    encoders = _nodes_by_class(prompt_json, TEXT_ENCODE_CLASS_TYPES)

    positive, negative = "", ""
    params: dict[str, Any] = {}

    if samplers:
        # Use the first sampler found.
        sampler = next(iter(samplers.values()))
        inputs = sampler.get("inputs", {}) or {}
        positive = _resolve_conditioning_text(prompt_json, inputs.get("positive"))
        negative = _resolve_conditioning_text(prompt_json, inputs.get("negative"))
        params.update(_extract_sampler_params(sampler))
    else:
        positive, negative = _heuristic_positive_negative(encoders, prompt_json)

    model_name = _find_model_name(prompt_json)
    if model_name:
        params["model"] = model_name

    result["positive"] = positive
    result["negative"] = negative
    result["params"] = params
    return result


# --------------------------------------------------------------------------- #
# Resolution helpers
# --------------------------------------------------------------------------- #


def _nodes_by_class(graph: dict, class_types: set) -> dict:
    return {
        nid: node
        for nid, node in graph.items()
        if isinstance(node, dict)
        and node.get("class_type") in class_types
    }


def _is_link(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and isinstance(value[0], (str, int))
    )


def _resolve_conditioning_text(graph: dict, value: Any, depth: int = 0) -> str:
    """Follow a conditioning link back to its source text."""

    if depth > 16 or not _is_link(value):
        # A plain string widget value.
        return _stringify(value)

    node_id = value[0]
    node = graph.get(node_id)
    if not isinstance(node, dict):
        return ""

    class_type = node.get("class_type")
    inputs = node.get("inputs", {}) or {}

    # If this is a text encoder, its ``text`` input holds the prompt string.
    if class_type in TEXT_ENCODE_CLASS_TYPES:
        return _resolve_conditioning_text(graph, inputs.get("text"), depth + 1)

    # Some nodes (e.g. conditioning combine/concat) have multiple conditioning
    # inputs; join them.
    text_parts = []
    for key in ("positive", "negative", "text_a", "text_b", "text"):
        if key in inputs:
            resolved = _resolve_conditioning_text(graph, inputs[key], depth + 1)
            if resolved:
                text_parts.append(resolved)
    if text_parts:
        return "\n".join(text_parts)

    return _stringify(value)


def _extract_sampler_params(sampler: dict) -> dict:
    inputs = sampler.get("inputs", {}) or {}
    params: dict[str, Any] = {}
    for key in ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"):
        if key in inputs:
            params[key] = inputs[key]
    return params


def _find_model_name(graph: dict) -> str:
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        if node.get("class_type") in MODEL_LOADER_CLASS_TYPES:
            inputs = node.get("inputs", {}) or {}
            for key in ("ckpt_name", "unet_name", "model_name"):
                value = inputs.get(key)
                if isinstance(value, str):
                    return value
    # LoRA loaders can hint at the model stack but aren't the base model.
    return ""


def _heuristic_positive_negative(encoders: dict, graph: dict) -> tuple:
    """When no sampler is present, guess positive/negative from encoders."""

    if not encoders:
        return "", ""
    texts = []
    for node in encoders.values():
        inputs = node.get("inputs", {}) or {}
        text = _resolve_conditioning_text(graph, inputs.get("text"))
        title = (node.get("_meta") or {}).get("title", "") if isinstance(node.get("_meta"), dict) else ""
        texts.append((text, title.lower()))

    if len(texts) == 1:
        return texts[0][0], ""

    # Anything whose title/text mentions "negative" is the negative prompt.
    positive_parts, negative_parts = [], []
    for text, title in texts:
        bucket = negative_parts if ("negative" in title or "negative" in text.lower()[:32]) else positive_parts
        if text:
            bucket.append(text)
    if not positive_parts and not negative_parts:
        # First encoder is conventionally positive.
        positive_parts.append(texts[0][0])
        negative_parts.extend(t for t, _ in texts[1:])
    return "\n".join(positive_parts), "\n".join(negative_parts)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)
