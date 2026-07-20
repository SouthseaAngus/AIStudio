"""ComfyUI client.

Submits an API-format graph to /prompt, polls /history until the job
completes, then downloads the resulting images via /view. Polling keeps the
dependency footprint to requests only (no websockets needed for v0.1).
"""

import time
import uuid

import requests


class ComfyClient:
    def __init__(self, cfg: dict, logger):
        self.host = cfg["comfyui"]["host"].rstrip("/")
        self.poll_interval = cfg["comfyui"]["poll_interval"]
        self.timeout = cfg["comfyui"]["timeout"]
        self.logger = logger
        self.client_id = f"aistudio-{uuid.uuid4().hex[:8]}"

    def check_available(self):
        try:
            r = requests.get(f"{self.host}/system_stats", timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            self.logger.fail(f"cannot reach ComfyUI at {self.host}: {e}")

    def submit(self, graph: dict) -> str:
        payload = {"prompt": graph, "client_id": self.client_id}
        try:
            r = requests.post(f"{self.host}/prompt", json=payload, timeout=30)
        except requests.RequestException as e:
            self.logger.fail(f"ComfyUI submit failed: {e}")
        if r.status_code != 200:
            self.logger.fail(
                f"ComfyUI rejected the workflow (HTTP {r.status_code}): {r.text}"
            )
        prompt_id = r.json().get("prompt_id")
        if not prompt_id:
            self.logger.fail(f"ComfyUI response had no prompt_id: {r.text}")
        return prompt_id

    def wait(self, prompt_id: str) -> dict:
        """Poll /history until the job appears with outputs, or time out."""
        start = time.time()
        while True:
            if time.time() - start > self.timeout:
                self.logger.fail(
                    f"generation timed out after {self.timeout}s (prompt {prompt_id})"
                )
            try:
                r = requests.get(f"{self.host}/history/{prompt_id}", timeout=30)
                r.raise_for_status()
            except requests.RequestException as e:
                self.logger.fail(f"ComfyUI history poll failed: {e}")
            history = r.json()
            if prompt_id in history:
                entry = history[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    self.logger.fail(
                        f"ComfyUI reported an execution error: {status}"
                    )
                if entry.get("outputs"):
                    return entry
            time.sleep(self.poll_interval)

    def download_images(self, history_entry: dict) -> list[bytes]:
        """Fetch every SaveImage output as PNG bytes."""
        images = []
        for output in history_entry.get("outputs", {}).values():
            for img in output.get("images", []):
                if img.get("type") != "output":
                    continue
                params = {
                    "filename": img["filename"],
                    "subfolder": img.get("subfolder", ""),
                    "type": img["type"],
                }
                try:
                    r = requests.get(f"{self.host}/view", params=params, timeout=60)
                    r.raise_for_status()
                except requests.RequestException as e:
                    self.logger.fail(f"failed to download {img['filename']}: {e}")
                images.append(r.content)
        if not images:
            self.logger.fail("generation completed but produced no images")
        return images
