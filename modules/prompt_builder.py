"""Prompt builder.

Turns a one-line user request into the structured generation spec via the
orchestrator LLM, then validates and clamps every value. The LLM chooses the
style, workflow, model capability, dimensions, CFG and steps — but never gets
to exceed the limits in config.yaml.
"""

def build_system_prompt(cfg: dict) -> str:
    clipart_bg = (
        cfg.get("styles", {}).get("clipart", {}).get("background", "plain white")
    )
    workflow_names = ", ".join(sorted(cfg["workflows"]["map"].keys()))
    model_caps = ", ".join(sorted(cfg["models"]["map"].keys()))
    return f"""You are the orchestrator for a local image-generation studio.
Given the user's request, respond with ONLY a JSON object, no prose, with exactly these keys:

{{
  "title": "Short Title Case name for the output folder, max 6 words",
  "style": "one of: photo, clipart, illustration, logo",
  "workflow": "one of: {workflow_names}",
  "model": "one of: {model_caps}",
  "positive": "the image generation prompt, written in the chosen style's language",
  "negative": "things to avoid",
  "cfg": 3.5,
  "steps": 30,
  "width": 1024,
  "height": 1024
}}

STYLE COMES FIRST. Decide the style before anything else:
- If the user says clip art, clipart, icon, flat, cartoon, sticker, simple graphic,
  logo, vector, diagram, or names a limited colour palette -> style is "clipart"
  (or "logo" for logos). This is mandatory: never upgrade a simple-graphic request
  to a photographic one.
- If the user asks for a drawing, painting, watercolour, sketch or similar ->
  style is "illustration".
- Only use style "photo" when the user asks for a photo or clearly implies
  realism. Do not default to photo merely because the subject is a physical object.

Prompt-writing rules per style:
- clipart / logo: write e.g. "simple flat clip art illustration of X, bold solid
  colours, clean thick outlines, minimal detail, no shading, no gradients,
  vector graphic style". Honour any colours the user names ("in red and grey").
  NEVER mention photography, lighting, lenses, bokeh, texture, realism or
  resolution. Use cfg 3.0 and workflow "clipart".
- BACKGROUND RULE (mandatory): the positive prompt MUST end with
  "on a {clipart_bg} background". Only if the user names a background colour,
  use theirs instead. Never use a white background unless the user asks for it.
- illustration: describe medium, line quality, palette and composition.
- photo: cover subject, setting, lighting and mood.

Other rules:
- The negative prompt is ignored by some workflows, so the positive prompt must
  fully specify the style on its own.
- cfg between 2.5 and 4.0 unless the user explicitly asks for stronger adherence.
- Choose dimensions to suit the content: clipart and logos are usually square.
- Respond with the JSON object only."""


REQUIRED = {
    "title": str,
    "style": str,
    "workflow": str,
    "model": str,
    "positive": str,
    "negative": str,
    "cfg": (int, float),
    "steps": int,
    "width": int,
    "height": int,
}

KNOWN_STYLES = ("photo", "clipart", "illustration", "logo")


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

    if spec["style"] not in KNOWN_STYLES:
        logger.log(f"WARN: unknown style '{spec['style']}', treating as 'photo'")
        spec["style"] = "photo"

    if spec["workflow"] not in cfg["workflows"]["map"]:
        logger.log(
            f"WARN: unknown workflow '{spec['workflow']}', "
            f"falling back to '{cfg['workflows']['default']}'"
        )
        spec["workflow"] = cfg["workflows"]["default"]

    # Belt and braces: a non-photo style must not land on a photo workflow.
    if spec["style"] in ("clipart", "logo") and "clipart" in cfg["workflows"]["map"]:
        if spec["workflow"] != "clipart":
            logger.log(
                f"WARN: style '{spec['style']}' but workflow "
                f"'{spec['workflow']}' — overriding to 'clipart'"
            )
            spec["workflow"] = "clipart"

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


def apply_model_limits(spec: dict, cfg: dict, logger) -> dict:
    """Cap steps for the checkpoint actually selected.

    Runs after any --model override, so the cap always matches the model that
    will be loaded (and Metadata.json records the steps really used).
    """
    ckpt = cfg["models"]["map"][spec["model"]]
    limit = cfg["models"]["step_limits"].get(ckpt)
    if limit is not None and spec["steps"] > limit:
        logger.log(f"Steps capped {spec['steps']} -> {limit} for {ckpt}")
        spec["steps"] = limit
    return spec
