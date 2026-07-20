"""Ollama client.

Uses /api/chat with format="json" and temperature 0 so the orchestrator
returns deterministic, machine-parseable output.
"""

import json

import requests


class OllamaClient:
    def __init__(self, cfg: dict, logger):
        self.host = cfg["ollama"]["host"].rstrip("/")
        self.model = cfg["ollama"]["orchestrator_model"]
        self.temperature = cfg["ollama"]["temperature"]
        self.logger = logger

    def check_available(self):
        """Confirm Ollama is up and the orchestrator model is installed."""
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            self.logger.fail(f"cannot reach Ollama at {self.host}: {e}")
        names = [m.get("name", "") for m in r.json().get("models", [])]
        # Accept exact match or match without tag (e.g. "qwen3.6" vs "qwen3.6:latest")
        base = self.model.split(":")[0]
        if not any(n == self.model or n.split(":")[0] == base for n in names):
            self.logger.fail(
                f"orchestrator model '{self.model}' not found in Ollama. "
                f"Installed: {', '.join(names) or '(none)'}"
            )

    def model_version(self) -> dict:
        """Return name + digest of the orchestrator model, for Metadata.json."""
        try:
            r = requests.post(
                f"{self.host}/api/show", json={"model": self.model}, timeout=10
            )
            r.raise_for_status()
            details = r.json().get("details", {})
            return {"name": self.model, "details": details}
        except requests.RequestException:
            return {"name": self.model, "details": "unavailable"}

    def structured_json(self, system_prompt: str, user_prompt: str) -> dict:
        """Ask the orchestrator for a JSON object. Fail loud on bad JSON."""
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": self.temperature},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            r = requests.post(f"{self.host}/api/chat", json=payload, timeout=300)
            r.raise_for_status()
        except requests.RequestException as e:
            self.logger.fail(f"Ollama request failed: {e}")

        content = r.json().get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            self.logger.fail(
                f"orchestrator did not return valid JSON ({e}). Raw output:\n{content}"
            )
