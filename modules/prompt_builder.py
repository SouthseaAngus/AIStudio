"""Prompt builder.

Turns a one-line user request into the structured generation spec via the
orchestrator LLM, then validates and clamps every value. The LLM chooses the
workflow, model capability, dimensions, CFG and steps — but never gets to
exceed the limits in config.yaml.
"""


def build_system_prompt(cfg: dict) -> str:
    workflow_names = ", ".join(sorted(cfg["workflows"]["map"].keys()))
    model_caps = ", ".join(sorted(cfg["models"]["map"].keys()))
    return f"""You are the orchestrator for a local image-generation studio.
Given the user's request, respond with ONLY a JSON object, no prose, with exactly these keys:

{{
  "title": "Short Title Case name for the output folder, max 6 words",
  "workflow": "one of: {workflow_names}",
  "model": "one of: {model_caps}",
  "positive": "a detailed, high-quality image generation prompt",
  "negative": "things to avoid",
  "cfg": 3.5,
  "steps": 30,
  "width": 1536,
  "height": 1024
}}

Rules:
- Choose the workflow that best matches the subject and requested orientation.
- Choose dimensions appropriate to the workflow (landscape wider than tall, portrait taller than wide, square equal).
- Write the positive prompt in rich descriptive language covering subject, setting, lighting, mood and style.
- Respond with the JSON object only."""


REQUIRED = {
    "title": str,
    "workflow": str,
    "model": str,
    "positive": str,
    "negative": str,
    "cfg": (int, float),
    "steps": int,
    "width": int,
    "height": int,
}


def _snap(value: int, multiple: int, maximum: int) -> int:
    value = max(multiple, min(int(value), maximum))
    return (value // multiple) * multiple


def validate_and_clamp(spec: dict, cfg: dict, logger) -> dict:
    """Fail loud on structural problems; clamp numeric excursions."""
    for key, typ in REQUIRED.items():
        if key not in spec:
            logger.fail(f"orchestrator JSON missing key: {key}. Got: {spec}")
        if key in ("steps", "width", "height") and isinstance(spec[key], float):
            spec[key] = int(spec[key])  # tolerate 30.0
        if not isinstance(spec[key], typ):
            logger.fail(f"orchestrator JSON key '{key}' has wrong type: {spec[key]!r}")

    g = cfg["generation"]

    if spec["workflow"] not in cfg["workflows"]["map"]:
        logger.log(
            f"WARN: unknown workflow '{spec['workflow']}', "
            f"falling back to '{cfg['workflows']['default']}'"
        )
        spec["workflow"] = cfg["workflows"]["default"]

    if spec["model"] not in cfg["models"]["map"]:
        logger.log(
            f"WARN: unknown model capability '{spec['model']}', "
            f"falling back to '{cfg['models']['default']}'"
        )
        spec["model"] = cfg["models"]["default"]

    spec["cfg"] = float(min(max(spec["cfg"], g["min_cfg"]), g["max_cfg"]))
    spec["steps"] = min(max(spec["steps"], g["min_steps"]), g["max_steps"])
    spec["width"] = _snap(spec["width"], g["dimension_multiple"], g["max_dimension"])
    spec["height"] = _snap(spec["height"], g["dimension_multiple"], g["max_dimension"])

    # Sanitise title for use as a folder name.
    safe = "".join(c for c in spec["title"] if c.isalnum() or c in " -_").strip()
    spec["title"] = safe or "Untitled"

    return spec
