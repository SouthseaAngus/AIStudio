"""Prompt builder.

Turns a one-line user request into the structured generation spec via the
orchestrator LLM, then validates and clamps every value. The LLM chooses the
image type (style), workflow, model capability, dimensions and steps — but
never gets to exceed the limits in config.yaml.

The image types themselves live in config.yaml under styles.types, so the
catalogue the LLM sees, the validation rules and `--list-styles` all come
from one place.
"""

FAMILY_RULES = {
    "photo": (
        "Photographic types. Describe subject, setting, light, mood and, where "
        "useful, lens or camera choices."
    ),
    "graphic": (
        "Graphic types. NEVER mention photography, lighting, lenses, bokeh, "
        "texture, realism or resolution. Honour any colours the user names "
        "(\"in red and grey\")."
    ),
    "art": (
        "Art and illustration types. Describe the medium, technique, line "
        "quality, palette and composition. NEVER use photographic language "
        "(lenses, bokeh, exposure, 'photo of')."
    ),
}


def _catalogue(cfg: dict) -> str:
    lines = []
    for name, st in cfg["styles"]["types"].items():
        entry = (
            f"- {name} [{st['family']}]: {st['description']}.\n"
            f"  Choose when: {st['choose_when']}.\n"
            f"  Positive prompt pattern (X = subject): \"{st['prompt']}\"\n"
            f"  Default workflow \"{st['workflow']}\", model \"{st['model']}\"."
        )
        if st.get("lock_workflow"):
            entry += " The workflow is fixed for this type."
        if st.get("background"):
            entry += (
                f"\n  BACKGROUND: the positive prompt MUST end with "
                f"\"on a {st['background']} background\" unless the user names "
                f"a background, in which case use theirs."
            )
        lines.append(entry)
    return "\n".join(lines)


def build_system_prompt(cfg: dict) -> str:
    types = cfg["styles"]["types"]
    style_names = ", ".join(types.keys())
    workflow_names = ", ".join(sorted(cfg["workflows"]["map"].keys()))
    model_caps = ", ".join(sorted(cfg["models"]["map"].keys()))
    default = cfg["styles"]["default"]
    text_max = cfg["styles"]["text"]["max_length"]
    families = "\n".join(f"- {k}: {v}" for k, v in FAMILY_RULES.items())
    return f"""You are the orchestrator for a local image-generation studio.
Given the user's request, respond with ONLY a JSON object, no prose, with exactly these keys:

{{
  "title": "Short Title Case name for the output folder, max 6 words",
  "style": "one of: {style_names}",
  "workflow": "one of: {workflow_names}",
  "model": "one of: {model_caps}",
  "positive": "the image generation prompt, following the chosen style's pattern",
  "negative": "extra things to avoid for this particular request (may be empty)",
  "text": "the exact words to appear in the image, or an empty string",
  "steps": 30,
  "width": 1024,
  "height": 1024
}}

STYLE COMES FIRST. Pick the image type before anything else, from this catalogue:

{_catalogue(cfg)}

Choosing the style:
- Match the user's words against "Choose when". The most specific match wins
  (a black-and-white portrait is "monochrome"; a portrait in watercolour is
  "watercolour"; a medium named by the user always beats the subject).
- Never upgrade a graphic or art request to a photographic type. Do not choose
  a photographic type merely because the subject is a physical object.
- If the request contains a line "Required style: NAME", use exactly that style.
- If nothing points to a type, use "{default}".

Vocabulary rules by family:
{families}

Writing the positive prompt:
- Start from the chosen style's pattern, replace X with a vivid description of
  the user's subject, and keep every style keyword. The negative prompt is
  ignored by some workflows, so the positive prompt must fully specify the style.

Text in the image:
- Put words in "text" only when they belong in the picture: the user quotes
  words, asks for a title, caption, slogan, name or sign, or the type
  traditionally carries words (a poster's place name, a logo's brand name).
  Otherwise "text" is "".
- Copy the user's spelling and capitalisation exactly. Keep it short, at most
  {text_max} characters; posters usually use the place name in capitals.
- Also write the words into the positive prompt in double quotes and say how
  they look and where they sit, e.g. 'the title "SOUTHSEA" in large bold art
  deco capitals across the top'. Never put any other words in quotes.

Other fields:
- workflow: use the style's default unless the user asks for a different shape
  (tall, wide, square); ignored where the workflow is fixed.
- model: use the style's default; use "fast_preview" if the user asks for speed
  or a draft, "highest_quality" if they ask for best quality.
- width/height: suit the content and the workflow's shape; graphic types are
  usually square.
- Respond with the JSON object only."""


REQUIRED = {
    "title": str,
    "style": str,
    "workflow": str,
    "model": str,
    "positive": str,
    "negative": str,
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
    types = cfg["styles"]["types"]

    if spec["style"] not in types:
        default = cfg["styles"]["default"]
        logger.log(f"WARN: unknown style '{spec['style']}', treating as '{default}'")
        spec["style"] = default
    st = types[spec["style"]]

    if spec["workflow"] not in cfg["workflows"]["map"]:
        logger.log(
            f"WARN: unknown workflow '{spec['workflow']}', "
            f"using style default '{st['workflow']}'"
        )
        spec["workflow"] = st["workflow"]

    # Belt and braces: fixed-shape types (clip art, logos, icons...) must not
    # land on another workflow, whatever the LLM suggested.
    if st.get("lock_workflow") and spec["workflow"] != st["workflow"]:
        logger.log(
            f"WARN: style '{spec['style']}' but workflow "
            f"'{spec['workflow']}' — overriding to '{st['workflow']}'"
        )
        spec["workflow"] = st["workflow"]

    if spec["model"] not in cfg["models"]["map"]:
        logger.log(
            f"WARN: unknown model capability '{spec['model']}', "
            f"using style default '{st['model']}'"
        )
        spec["model"] = st["model"]

    # Guidance comes from the style, not the LLM, so every run of a type is
    # steered the same way.
    spec["cfg"] = float(min(max(st["cfg"], g["min_cfg"]), g["max_cfg"]))

    # The style's avoid-list always heads the negative prompt.
    extra = spec["negative"].strip()
    spec["negative"] = f"{st['avoid']}, {extra}" if extra else st["avoid"]

    spec = _apply_text(spec, cfg, logger)

    spec["steps"] = min(max(spec["steps"], g["min_steps"]), g["max_steps"])
    spec["width"] = _snap(spec["width"], g["dimension_multiple"], g["max_dimension"])
    spec["height"] = _snap(spec["height"], g["dimension_multiple"], g["max_dimension"])

    # Sanitise title for use as a folder name.
    safe = "".join(c for c in spec["title"] if c.isalnum() or c in " -_").strip()
    spec["title"] = safe or "Untitled"

    return spec


TEXT_WORDS = ("small text", "text", "lettering", "letters", "words", "typography",
              "watermark", "signature", "caption", "logo text")


def _apply_text(spec: dict, cfg: dict, logger) -> dict:
    """Make requested words legible: quote them, use a model that can spell,
    raise guidance, and stop the negative prompt fighting them."""
    t = cfg["styles"]["text"]
    text = spec.get("text", "")
    text = text.strip().strip('"\'').strip() if isinstance(text, str) else ""
    if len(text) > t["max_length"]:
        logger.log(f"WARN: text is {len(text)} characters; beyond {t['max_length']} "
                   f"FLUX often misspells it. Shorter wording renders better.")
    spec["text"] = text
    if not text:
        return spec

    if f'"{text}"' not in spec["positive"]:
        spec["positive"] = (
            spec["positive"].rstrip(" ,.")
            + f', with the words "{text}" in large, clear, bold lettering, spelled exactly'
        )
    if spec["model"] != t["model"]:
        logger.log(f"Text requested: model {spec['model']} -> {t['model']} (better spelling)")
        spec["model"] = t["model"]
    spec["cfg"] = max(spec["cfg"], float(t["guidance"]))
    kept = [w.strip() for w in spec["negative"].split(",")
            if w.strip() and w.strip().lower() not in TEXT_WORDS]
    spec["negative"] = ", ".join(kept)
    logger.log(f'Text to render: "{text}"')
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


def list_styles(cfg: dict) -> str:
    """Human-readable catalogue for `controller.py --list-styles`."""
    out = []
    for name, st in cfg["styles"]["types"].items():
        out.append(
            f"{name:<15} {st['family']:<8} {st['description']}\n"
            f"{'':<24}e.g. \"{st['example']}\""
        )
    return "\n".join(out)
