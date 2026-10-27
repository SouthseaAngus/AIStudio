"""Metadata assembly.

Everything needed to reproduce a generation years later: prompt, workflow,
seed, sampler settings, model, timings, the git commit of AIStudio itself,
and the Ollama orchestrator version.
"""

import subprocess
from datetime import datetime
from pathlib import Path


def git_commit(repo_dir: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return "not-a-git-repository"
    except (subprocess.SubprocessError, FileNotFoundError):
        return "git-unavailable"


def build_metadata(
    *,
    user_prompt: str,
    spec: dict,
    seed: int,
    batch_size: int,
    workflow_name: str,
    checkpoint: str,
    ollama_model: dict,
    started: datetime,
    finished: datetime,
    repo_dir: Path,
) -> dict:
    return {
        "user_prompt": user_prompt,
        "title": spec["title"],
        "style": spec["style"],
        "positive": spec["positive"],
        "negative": spec["negative"],
        "workflow": workflow_name,
        "seed": seed,
        "cfg": spec["cfg"],
        "steps": spec["steps"],
        "width": spec["width"],
        "height": spec["height"],
        "batch_size": batch_size,
        "model_capability": spec["model"],
        "checkpoint": checkpoint,
        "orchestrator": ollama_model,
        "generation_started": started.isoformat(timespec="seconds"),
        "generation_finished": finished.isoformat(timespec="seconds"),
        "generation_seconds": round((finished - started).total_seconds(), 1),
        "git_commit": git_commit(repo_dir),
        "aistudio_version": "0.1",
    }
