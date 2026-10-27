#!/usr/bin/env python3
"""AIStudio controller — v0.1

Usage:
    python controller.py "A red kite flying over Southsea Castle at sunrise"
    python controller.py "..." --workflow portrait --count 3
    python controller.py "..." --seed 12345
    python controller.py "..." --dry-run          # show the orchestrator JSON, generate nothing

Flow:
    Prompt received -> Ollama orchestration -> workflow loaded -> parameters
    injected -> ComfyUI generation -> images + sidecars written to the dated
    run folder.
"""

import argparse
import random
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from modules.logger import RunLogger
from modules.config import load_config
from modules.ollama_client import OllamaClient
from modules.comfy_client import ComfyClient
from modules.workflow_manager import WorkflowManager
from modules.image_manager import ImageManager
from modules import prompt_builder, metadata


def main():
    parser = argparse.ArgumentParser(description="AIStudio controller")
    parser.add_argument("prompt", help="one-line description of the image you want")
    parser.add_argument("--workflow", help="override the LLM's workflow choice")
    parser.add_argument("--model", help="override the LLM's model capability choice")
    parser.add_argument("--seed", type=int, help="fixed seed for reproducibility")
    parser.add_argument("--count", type=int, help="number of images to generate")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run orchestration only and print the resulting spec",
    )
    args = parser.parse_args()

    logger = RunLogger()
    logger.log("Prompt received")

    cfg = load_config(BASE_DIR / "config.yaml", logger)

    ollama = OllamaClient(cfg, logger)
    ollama.check_available()

    comfy = ComfyClient(cfg, logger)
    if not args.dry_run:
        comfy.start_if_needed()  # overlaps ComfyUI cold start with orchestration

    system_prompt = prompt_builder.build_system_prompt(cfg)
    spec = ollama.structured_json(system_prompt, args.prompt)
    logger.log("Ollama completed")

    spec = prompt_builder.validate_and_clamp(spec, cfg, logger)
    if args.workflow:
        if args.workflow not in cfg["workflows"]["map"]:
            logger.fail(f"--workflow '{args.workflow}' not in workflows.map")
        spec["workflow"] = args.workflow
    if args.model:
        if args.model not in cfg["models"]["map"]:
            logger.fail(f"--model '{args.model}' not in models.map")
        spec["model"] = args.model
    spec = prompt_builder.apply_model_limits(spec, cfg, logger)

    if args.dry_run:
        import json as _json

        logger.log("Dry run — orchestrator spec:")
        print(_json.dumps(spec, indent=2, ensure_ascii=False))
        return

    comfy.check_available()

    workflows = WorkflowManager(cfg, logger, BASE_DIR)
    graph = workflows.load(spec["workflow"])
    logger.log("Workflow loaded")

    seed = args.seed if args.seed is not None else random.randint(0, 2**32 - 1)
    batch = args.count if args.count is not None else cfg["generation"]["batch_size"]
    graph = workflows.inject(graph, spec, seed, batch)

    started = datetime.now()
    prompt_id = comfy.submit(graph)
    logger.log(f"Generation started (seed {seed}, prompt {prompt_id})")

    history = comfy.wait(prompt_id)
    finished = datetime.now()
    logger.log("Generation finished")

    images = comfy.download_images(history)

    manager = ImageManager(cfg, logger)
    run_dir = manager.create_run_dir(spec["title"])
    logger.attach_file(run_dir)

    manager.save_images(run_dir, images)
    manager.save_json(run_dir, "Prompt.json", spec)
    manager.save_json(run_dir, "Workflow.json", graph)
    meta = metadata.build_metadata(
        user_prompt=args.prompt,
        spec=spec,
        seed=seed,
        batch_size=batch,
        workflow_name=cfg["workflows"]["map"][spec["workflow"]],
        checkpoint=cfg["models"]["map"][spec["model"]],
        ollama_model=ollama.model_version(),
        started=started,
        finished=finished,
        repo_dir=BASE_DIR,
    )
    manager.save_json(run_dir, "Metadata.json", meta)

    logger.log(f"Saved {len(images)} image(s) to {run_dir}")


if __name__ == "__main__":
    main()
