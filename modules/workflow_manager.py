"""Workflow manager.

Loads a ComfyUI *API-format* workflow JSON and injects the generation spec.

Nodes are located by their _meta title first ("Positive Prompt",
"Negative Prompt"), then by class_type. This means you can export any
working graph from your own ComfyUI (enable Dev Mode, then
"Save (API format)"), title the two text nodes accordingly, drop the file
into workflows/, and it will work without touching this code.
"""

import copy
import json
from pathlib import Path


def _find_by_title(graph: dict, title: str):
    for node_id, node in graph.items():
        if node.get("_meta", {}).get("title", "").lower() == title.lower():
            return node_id
    return None


def _find_by_class(graph: dict, *class_types: str):
    return [
        node_id
        for node_id, node in graph.items()
        if node.get("class_type") in class_types
    ]


class WorkflowManager:
    def __init__(self, cfg: dict, logger, base_dir: Path):
        self.cfg = cfg
        self.logger = logger
        self.dir = base_dir / cfg["workflows"]["dir"]

    def load(self, capability: str) -> dict:
        name = self.cfg["workflows"]["map"][capability]
        path = self.dir / f"{name}.json"
        if not path.is_file():
            self.logger.fail(f"workflow file not found: {path}")
        try:
            with path.open("r", encoding="utf-8") as f:
                graph = json.load(f)
        except json.JSONDecodeError as e:
            self.logger.fail(f"workflow parse error in {path}: {e}")
        if not isinstance(graph, dict) or "nodes" in graph:
            self.logger.fail(
                f"{path} looks like a UI-format export. Re-export with "
                f"'Save (API format)' (enable Dev Mode in ComfyUI settings)."
            )
        return graph

    def inject(self, graph: dict, spec: dict, seed: int, batch_size: int) -> dict:
        g = copy.deepcopy(graph)

        # Positive / negative prompts — by title, falling back to node order.
        pos = _find_by_title(g, "Positive Prompt")
        neg = _find_by_title(g, "Negative Prompt")
        if pos is None or neg is None:
            encoders = _find_by_class(g, "CLIPTextEncode")
            if len(encoders) >= 2:
                pos = pos or encoders[0]
                neg = neg or encoders[1]
        if pos is None:
            self.logger.fail(
                "no positive prompt node found. Title a CLIPTextEncode node "
                "'Positive Prompt' in your workflow."
            )
        g[pos]["inputs"]["text"] = spec["positive"]
        if neg is not None:
            g[neg]["inputs"]["text"] = spec["negative"]

        # Checkpoint — model-agnostic capability mapping.
        ckpt = self.cfg["models"]["map"][spec["model"]]
        for node_id in _find_by_class(g, "CheckpointLoaderSimple"):
            g[node_id]["inputs"]["ckpt_name"] = ckpt
        for node_id in _find_by_class(g, "UNETLoader"):
            g[node_id]["inputs"]["unet_name"] = ckpt

        # Latent dimensions.
        latents = _find_by_class(g, "EmptySD3LatentImage", "EmptyLatentImage")
        if not latents:
            self.logger.fail("no empty-latent node found in workflow")
        for node_id in latents:
            g[node_id]["inputs"]["width"] = spec["width"]
            g[node_id]["inputs"]["height"] = spec["height"]
            g[node_id]["inputs"]["batch_size"] = batch_size

        # Sampler: seed and steps. FLUX guidance is carried by a FluxGuidance
        # node if present; KSampler cfg stays as authored (1.0 for FLUX).
        samplers = _find_by_class(g, "KSampler", "KSamplerAdvanced")
        if not samplers:
            self.logger.fail("no KSampler node found in workflow")
        for node_id in samplers:
            inputs = g[node_id]["inputs"]
            if "seed" in inputs:
                inputs["seed"] = seed
            if "noise_seed" in inputs:
                inputs["noise_seed"] = seed
            inputs["steps"] = spec["steps"]

        flux_guidance = _find_by_class(g, "FluxGuidance")
        if flux_guidance:
            for node_id in flux_guidance:
                g[node_id]["inputs"]["guidance"] = spec["cfg"]
        else:
            # Non-FLUX graph: cfg goes straight onto the sampler.
            for node_id in samplers:
                g[node_id]["inputs"]["cfg"] = spec["cfg"]

        return g
