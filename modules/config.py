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

    cfg["output"]["root"] = str(Path(cfg["output"]["root"]).expanduser())
    return cfg
