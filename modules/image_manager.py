"""Image manager.

Creates the dated run folder — Output/YYYY/MM/YYYY-MM-DD Title/ — and writes
images plus the reproducibility sidecars (Prompt.json, Workflow.json,
Metadata.json). If the folder already exists, a numeric suffix is appended
rather than overwriting anything.
"""

import json
from datetime import datetime
from pathlib import Path


class ImageManager:
    def __init__(self, cfg: dict, logger):
        self.root = Path(cfg["output"]["root"])
        self.logger = logger

    def create_run_dir(self, title: str) -> Path:
        now = datetime.now()
        base = self.root / now.strftime("%Y") / now.strftime("%m")
        name = f"{now.strftime('%Y-%m-%d')} {title}"
        run_dir = base / name
        suffix = 2
        while run_dir.exists():
            run_dir = base / f"{name} ({suffix})"
            suffix += 1
        run_dir.mkdir(parents=True)
        return run_dir

    def save_images(self, run_dir: Path, images: list[bytes]) -> list[Path]:
        paths = []
        for i, data in enumerate(images, start=1):
            path = run_dir / f"Image_{i:02d}.png"
            path.write_bytes(data)
            paths.append(path)
        return paths

    def save_json(self, run_dir: Path, filename: str, payload: dict):
        path = run_dir / filename
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return path
