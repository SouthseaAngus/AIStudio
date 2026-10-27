"""Fail-loud config loader.

Any missing key or malformed value aborts immediately with a message naming
the key, in the same spirit as cameras.conf parsing in the photography
pipeline.
"""

from pathlib import Path

import yaml


REQUIRED_KEYS = [
    ("ollama", "host"),
    ("ollama", "orchestrator_model"),
    ("ollama", "temperature"),
    ("ollama", "num_ctx"),
    ("comfyui", "host"),
    ("comfyui", "poll_interval"),
    ("comfyui", "timeout"),
    ("comfyui", "launchd_label"),
    ("comfyui", "startup_timeout"),
    ("output", "root"),
    ("workflows", "dir"),
    ("workflows", "map"),
    ("workflows", "default"),
    ("models", "map"),
    ("models", "default"),
    ("models", "step_limits"),
    ("styles", "default"),
    ("styles", "types"),
    ("generation", "min_steps"),
    ("generation", "max_steps"),
    ("generation", "min_cfg"),
    ("generation", "max_cfg"),
    ("generation", "dimension_multiple"),
    ("generation", "max_dimension"),
    ("generation", "batch_size"),
]


def load_config(path: str, logger) -> dict:
    p = Path(path)
    if not p.is_file():
        logger.fail(f"config file not found: {p}")
    try:
        with p.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except yaml.YAMLError as e:
        logger.fail(f"config parse error in {p}: {e}")

    if not isinstance(cfg, dict):
        logger.fail(f"config root is not a mapping in {p}")

    for section, key in REQUIRED_KEYS:
        if section not in cfg or not isinstance(cfg[section], dict):
            logger.fail(f"config missing section: {section}")
        if key not in cfg[section]:
            logger.fail(f"config missing key: {section}.{key}")

    if cfg["workflows"]["default"] not in cfg["workflows"]["map"]:
        logger.fail("config: workflows.default is not a key of workflows.map")
    if cfg["models"]["default"] not in cfg["models"]["map"]:
        logger.fail("config: models.default is not a key of models.map")

    if not isinstance(cfg["models"]["step_limits"], dict):
        logger.fail("config: models.step_limits must be a mapping (may be empty: {})")
    for ckpt, limit in cfg["models"]["step_limits"].items():
        if not isinstance(limit, int) or limit < 1:
            logger.fail(f"config: models.step_limits['{ckpt}'] must be a positive integer")

    _check_styles(cfg, logger)

    cfg["output"]["root"] = str(Path(cfg["output"]["root"]).expanduser())
    return cfg


STYLE_FIELDS = (
    "family", "description", "choose_when", "prompt", "avoid",
    "workflow", "model", "cfg", "example",
)
STYLE_FAMILIES = ("photo", "graphic", "art")


def _check_styles(cfg: dict, logger):
    """Fail loud on any malformed image type in styles.types."""
    types = cfg["styles"]["types"]
    if not isinstance(types, dict) or not types:
        logger.fail("config: styles.types must be a non-empty mapping")
    if cfg["styles"]["default"] not in types:
        logger.fail("config: styles.default is not a key of styles.types")
    for name, st in types.items():
        where = f"styles.types.{name}"
        if not isinstance(st, dict):
            logger.fail(f"config: {where} must be a mapping")
        for field in STYLE_FIELDS:
            if field not in st:
                logger.fail(f"config missing key: {where}.{field}")
        if st["family"] not in STYLE_FAMILIES:
            logger.fail(f"config: {where}.family must be one of {', '.join(STYLE_FAMILIES)}")
        if st["workflow"] not in cfg["workflows"]["map"]:
            logger.fail(f"config: {where}.workflow '{st['workflow']}' is not a key of workflows.map")
        if st["model"] not in cfg["models"]["map"]:
            logger.fail(f"config: {where}.model '{st['model']}' is not a key of models.map")
        if not isinstance(st["cfg"], (int, float)) or isinstance(st["cfg"], bool):
            logger.fail(f"config: {where}.cfg must be a number")
        if "lock_workflow" in st and not isinstance(st["lock_workflow"], bool):
            logger.fail(f"config: {where}.lock_workflow must be true or false")
        if "background" in st and not isinstance(st["background"], str):
            logger.fail(f"config: {where}.background must be a string")
