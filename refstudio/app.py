#!/usr/bin/env python3
"""RefStudio: FLUX.2 image generation from reference photos, in your browser.

    cd ~/AIStudio && source .venv/bin/activate
    python refstudio/app.py

Opens http://127.0.0.1:8765. Drop in up to 16 reference photos, give the run a
label and a prompt, and generate. Each run is saved like any AIStudio run:

    ~/AIStudio/Output/YYYY/MM/YYYY-MM-DD <Label>/
        Image_01.png ...        the results
        references/             the photos you dropped in
        Metadata.json           prompt, settings, seeds and timings
        Prompt.json, Workflow.json, Generation.log

Only this computer can reach the page (it listens on 127.0.0.1).
"""

import base64
import copy
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import requests

HERE = Path(__file__).resolve().parent
PORT = int(os.environ.get("REFSTUDIO_PORT", "8765"))
COMFY = os.environ.get("REFSTUDIO_COMFY", "http://127.0.0.1:8188").rstrip("/")
OLLAMA = os.environ.get("REFSTUDIO_OLLAMA", "http://127.0.0.1:11434").rstrip("/")
OUTPUT_ROOT = Path(os.environ.get("REFSTUDIO_OUTPUT", "~/AIStudio/Output")).expanduser()
LAUNCHD_LABEL = "com.angus.aistudio.comfyui"

MAX_REFS = 16
DOCUMENTED_REFS = 10        # FLUX.2's published limit; more still runs, with less certainty
REF_BUDGET_MP = 4.0         # total reference pixels: 1-4 refs at 1 MP each, 16 at 0.25 MP
MAX_BODY = 400 * 1024 * 1024

FLUX2_UNET = os.environ.get("REFSTUDIO_UNET", "flux2-dev-Q6_K.gguf")
FLUX2_TE = "mistral_3_small_flux2_bf16.safetensors"
FLUX2_VAE = "flux2-vae.safetensors"

SHAPES = {
    "landscape": (1536, 1024),
    "portrait": (1024, 1536),
    "square": (1248, 1248),
    "wide": (1792, 1008),
}

JOB_LOCK = threading.Lock()
JOBS = {}            # id -> job dict
CURRENT = {"id": None}


# ---------------------------------------------------------------- helpers

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_name(s, fallback="Untitled", limit=60):
    s = re.sub(r"[^A-Za-z0-9 \-_'&,()]", "", str(s or "")).strip()
    return (s[:limit].strip() or fallback)


def ref_megapixels(n):
    return round(min(1.0, max(0.25, REF_BUDGET_MP / max(n, 1))), 2)


def graph_flux2(images, prompt, seed, steps, guidance, width, height, prefix):
    mp = ref_megapixels(len(images))
    unet = ({"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": FLUX2_UNET}}
            if FLUX2_UNET.endswith(".gguf") else
            {"class_type": "UNETLoader", "inputs": {"unet_name": FLUX2_UNET, "weight_dtype": "default"}})
    g = {
        "1": unet,
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": FLUX2_TE, "type": "flux2"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": FLUX2_VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
    }
    cond = ["4", 0]
    for i, name in enumerate(images):
        nid = f"r{i}"
        g[nid] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g[f"{nid}s"] = {"class_type": "ImageScaleToTotalPixels", "inputs": {
            "image": [nid, 0], "upscale_method": "lanczos", "megapixels": mp, "resolution_steps": 16}}
        g[f"{nid}e"] = {"class_type": "VAEEncode", "inputs": {"pixels": [f"{nid}s", 0], "vae": ["3", 0]}}
        g[f"{nid}r"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": cond, "latent": [f"{nid}e", 0]}}
        cond = [f"{nid}r", 0]
    g.update({
        "5": {"class_type": "FluxGuidance", "inputs": {"conditioning": cond, "guidance": guidance}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "7": {"class_type": "Flux2Scheduler", "inputs": {"steps": steps, "width": width, "height": height}},
        "8": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "10": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["5", 0]}},
        "11": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["8", 0], "guider": ["10", 0], "sampler": ["9", 0],
            "sigmas": ["7", 0], "latent_image": ["6", 0]}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {"images": ["12", 0], "filename_prefix": prefix}},
    })
    return g


class JobError(Exception):
    pass


def _combo_options(spec):
    if isinstance(spec, list) and spec:
        if isinstance(spec[0], list):
            return spec[0]
        if spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
            return spec[1].get("options")
    return None


def preflight(graph, info):
    homes = {FLUX2_UNET: "ComfyUI/models/diffusion_models/", FLUX2_TE: "ComfyUI/models/text_encoders/",
             FLUX2_VAE: "ComfyUI/models/vae/"}
    for nid, node in graph.items():
        cls = node["class_type"]
        if cls not in info:
            if cls == "UnetLoaderGGUF":
                raise JobError("The ComfyUI-GGUF custom node isn't loaded. Install it and restart ComfyUI.")
            raise JobError(f"This ComfyUI has no '{cls}' node. Update ComfyUI and restart it.")
        spec = info[cls]["input"]
        required = spec.get("required", {})
        known = {**required, **spec.get("optional", {})}
        for name in list(node["inputs"]):
            if name not in known:
                del node["inputs"][name]
        for name, s in required.items():
            if name not in node["inputs"]:
                raise JobError(f"{cls} needs input '{name}', which RefStudio doesn't set.")
            opts = _combo_options(s)
            val = node["inputs"][name]
            if opts is not None and isinstance(val, str) and val not in opts and cls != "LoadImage":
                where = homes.get(val)
                raise JobError(f"Model '{val}' not found" + (f": put it in {where} and restart ComfyUI." if where else "."))


def comfy_up():
    try:
        return requests.get(f"{COMFY}/system_stats", timeout=5).ok
    except requests.RequestException:
        return False


def ensure_comfy(job):
    if comfy_up():
        return
    job_update(job, state="starting", message="Starting ComfyUI")
    try:
        subprocess.run(["launchctl", "kickstart", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"],
                       capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pass
    deadline = time.time() + 180
    while time.time() < deadline:
        if job.get("cancel"):
            raise JobError("Cancelled")
        time.sleep(2)
        if comfy_up():
            return
    raise JobError(f"ComfyUI isn't answering at {COMFY}. Start it and try again.")


def unload_ollama(job):
    """Free the memory held by any loaded Ollama models (FLUX.2 needs ~65 GB)."""
    try:
        loaded = requests.get(f"{OLLAMA}/api/ps", timeout=5).json().get("models", [])
    except (requests.RequestException, ValueError):
        return []
    names = []
    for m in loaded:
        name = m.get("name") or m.get("model")
        try:
            requests.post(f"{OLLAMA}/api/generate", json={"model": name, "keep_alive": 0}, timeout=30)
            names.append(name)
        except requests.RequestException:
            pass
    if names:
        job_log(job, f"Unloaded Ollama models: {', '.join(names)}")
    return names


def upload(path):
    with open(path, "rb") as f:
        r = requests.post(f"{COMFY}/upload/image", files={"image": (path.name, f, "image/jpeg")},
                          data={"overwrite": "true", "subfolder": "refstudio"}, timeout=120)
    if not r.ok:
        raise JobError(f"Upload of {path.name} to ComfyUI failed: HTTP {r.status_code}")
    j = r.json()
    return f"{j['subfolder']}/{j['name']}" if j.get("subfolder") else j["name"]


def run_prompt(graph, job):
    r = requests.post(f"{COMFY}/prompt", json={"prompt": graph, "client_id": "refstudio"}, timeout=60)
    if r.status_code != 200:
        raise JobError(f"ComfyUI rejected the job: {r.text[:500]}")
    pid = r.json()["prompt_id"]
    job["comfy_prompt"] = pid
    while True:
        time.sleep(2)
        if job.get("cancel"):
            raise JobError("Cancelled")
        try:
            h = requests.get(f"{COMFY}/history/{pid}", timeout=30).json()
        except (requests.RequestException, ValueError):
            if not comfy_up():
                raise JobError("ComfyUI stopped during generation. It may have run out of memory: "
                               "check ~/ComfyUI/user/comfyui.log.")
            continue
        if pid in h:
            status = h[pid].get("status", {})
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                detail = msgs[-1][1].get("exception_message", "").strip() if msgs else ""
                raise JobError(f"ComfyUI error: {detail or 'see ~/ComfyUI/user/comfyui.log'}")
            if h[pid].get("outputs"):
                return h[pid]["outputs"]


def fetch_images(outputs):
    out = []
    for o in outputs.values():
        for img in o.get("images", []):
            if img.get("type") != "output":
                continue
            r = requests.get(f"{COMFY}/view", params={"filename": img["filename"],
                             "subfolder": img.get("subfolder", ""), "type": "output"}, timeout=120)
            r.raise_for_status()
            out.append(r.content)
    if not out:
        raise JobError("ComfyUI finished but returned no image.")
    return out


# ---------------------------------------------------------------- jobs

def job_update(job, **kw):
    job.update(kw)
    job["updated"] = time.time()


def job_log(job, msg):
    line = f"{now()}  {msg}"
    job.setdefault("log", []).append(line)
    if job.get("run_dir"):
        with open(Path(job["run_dir"]) / "Generation.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    print(line, flush=True)


def rel_url(path):
    return "/files/" + quote(Path(path).relative_to(OUTPUT_ROOT).as_posix())


def make_run_dir(label):
    d = datetime.now()
    base = OUTPUT_ROOT / f"{d:%Y}" / f"{d:%m}" / f"{d:%Y-%m-%d} {label}"
    run, n = base, 2
    while run.exists():
        run = base.with_name(f"{base.name} ({n})")
        n += 1
    (run / "references").mkdir(parents=True)
    return run


def run_job(job, req):
    started = datetime.now()
    try:
        run_dir = Path(job["run_dir"])
        job_log(job, f"Prompt received: {req['prompt']}")
        ref_paths = sorted((run_dir / "references").iterdir())
        ensure_comfy(job)
        if req["unload_ollama"]:
            unload_ollama(job)
        job_update(job, state="uploading", message=f"Sending {len(ref_paths)} reference(s) to ComfyUI")
        names = [upload(p) for p in ref_paths]
        info = requests.get(f"{COMFY}/object_info", timeout=60).json()
        w, h = SHAPES[req["shape"]]
        per_image = []
        for i in range(req["count"]):
            seed = (req["seed"] + i) % (2**32)
            graph = graph_flux2(names, req["prompt"], seed, req["steps"], req["guidance"], w, h,
                                f"refstudio/{safe_name(req['label'])}")
            preflight(graph, info)
            if i == 0:
                (run_dir / "Workflow.json").write_text(json.dumps(graph, indent=2))
            job_update(job, state="generating", index=i + 1,
                       message=f"Generating image {i + 1} of {req['count']} (seed {seed})",
                       image_started=time.time())
            job_log(job, f"Generation started: image {i + 1}, seed {seed}")
            t0 = time.time()
            imgs = fetch_images(run_prompt(copy.deepcopy(graph), job))
            secs = round(time.time() - t0, 1)
            dest = run_dir / f"Image_{i + 1:02d}.png"
            dest.write_bytes(imgs[0])
            per_image.append({"file": dest.name, "seed": seed, "seconds": secs})
            job["images"].append(rel_url(dest))
            job_log(job, f"Saved {dest.name} in {secs:.0f}s")
        finished = datetime.now()
        write_metadata(run_dir, req, per_image, len(ref_paths), started, finished, "done")
        job_update(job, state="done", message=f"Done: {len(per_image)} image(s)", finished=time.time())
        job_log(job, f"Saved {len(per_image)} image(s) to {run_dir}")
    except JobError as e:
        cancelled = str(e) == "Cancelled"
        job_update(job, state="cancelled" if cancelled else "error", message=str(e), finished=time.time())
        job_log(job, ("Cancelled" if cancelled else f"ERROR: {e}"))
        write_metadata(Path(job["run_dir"]), req, [], 0, started, datetime.now(),
                       "cancelled" if cancelled else "error", str(e))
        tidy_failed_run(job, cancelled)
    except Exception as e:  # unexpected: report rather than kill the server
        job_update(job, state="error", message=f"Unexpected error: {e}", finished=time.time())
        job_log(job, f"ERROR: unexpected {e!r}")
    finally:
        with JOB_LOCK:
            CURRENT["id"] = None


def tidy_failed_run(job, cancelled):
    """A cancelled run with no images is removed; a failed one is kept, renamed
    '(failed)', so its Generation.log can be read. Runs with images are kept."""
    run_dir = Path(job["run_dir"])
    if job.get("images") or not run_dir.is_dir():
        return
    try:
        if cancelled:
            shutil.rmtree(run_dir)
        else:
            dest = run_dir.with_name(run_dir.name + " (failed)")
            if not dest.exists():
                run_dir.rename(dest)
                job["run_dir"] = str(dest)
                job["folder"] = dest.relative_to(OUTPUT_ROOT).as_posix()
    except OSError:
        pass


def write_metadata(run_dir, req, per_image, n_refs, started, finished, status, error=""):
    w, h = SHAPES[req["shape"]]
    meta = {
        "app": "refstudio",
        "status": status,
        "error": error,
        "title": req["label"],
        "user_prompt": req["prompt"],
        "positive": req["prompt"],
        "negative": "",
        "style": None,
        "workflow": "flux2_reference",
        "model_capability": "flux2_reference",
        "checkpoint": FLUX2_UNET,
        "text_encoder": FLUX2_TE,
        "seed": req["seed"],
        "steps": req["steps"],
        "cfg": req["guidance"],
        "shape": req["shape"],
        "width": w,
        "height": h,
        "references": n_refs,
        "reference_megapixels": ref_megapixels(n_refs) if n_refs else None,
        "images": per_image,
        "batch_size": len(per_image),
        "generation_started": started.isoformat(timespec="seconds"),
        "generation_finished": finished.isoformat(timespec="seconds"),
        "generation_seconds": round(sum(p["seconds"] for p in per_image), 1),
    }
    (run_dir / "Metadata.json").write_text(json.dumps(meta, indent=2))
    (run_dir / "Prompt.json").write_text(json.dumps({
        "title": req["label"], "positive": req["prompt"], "steps": req["steps"],
        "cfg": req["guidance"], "width": w, "height": h}, indent=2))


def start_job(body):
    label = safe_name(body.get("label"), "Reference Run")
    prompt = str(body.get("prompt") or "").strip()
    refs = body.get("refs") or []
    if not prompt:
        raise ValueError("Write a prompt first.")
    if len(refs) > MAX_REFS:
        raise ValueError(f"At most {MAX_REFS} reference images.")
    shape = body.get("shape") if body.get("shape") in SHAPES else "landscape"
    try:
        steps = min(max(int(body.get("steps") or 28), 4), 60)
        guidance = min(max(float(body.get("guidance") or 4.0), 1.0), 10.0)
        count = min(max(int(body.get("count") or 1), 1), 8)
        seed = int(body["seed"]) if str(body.get("seed", "")).strip() else random.randint(0, 2**32 - 1)
    except (TypeError, ValueError):
        raise ValueError("Steps, guidance, count and seed must be numbers.")
    req = {"label": label, "prompt": prompt, "shape": shape, "steps": steps, "guidance": guidance,
           "count": count, "seed": seed % (2**32), "unload_ollama": bool(body.get("unload_ollama", True))}

    with JOB_LOCK:
        if CURRENT["id"]:
            raise RuntimeError("A generation is already running.")
        run_dir = make_run_dir(label)
        for i, ref in enumerate(refs, 1):
            data = str(ref.get("data", ""))
            if "," in data:
                data = data.split(",", 1)[1]
            try:
                raw = base64.b64decode(data, validate=True)
            except ValueError:
                raise ValueError(f"Reference {i} isn't a readable image.")
            stem = re.sub(r"^\d+\s+", "", Path(str(ref.get("name") or f"ref{i}")).stem)
            stem = safe_name(stem, f"ref{i}", 40)
            (run_dir / "references" / f"{i:02d} {stem}.jpg").write_bytes(raw)
        job = {"id": uuid.uuid4().hex[:10], "state": "queued", "message": "Queued", "index": 0,
               "count": count, "images": [], "log": [], "created": time.time(),
               "run_dir": str(run_dir), "folder": run_dir.relative_to(OUTPUT_ROOT).as_posix(),
               "label": label, "seed": req["seed"]}
        JOBS[job["id"]] = job
        CURRENT["id"] = job["id"]
    threading.Thread(target=run_job, args=(job, req), daemon=True).start()
    return job


def public_job(job):
    keys = ("id", "state", "message", "index", "count", "images", "created", "finished",
            "image_started", "folder", "label", "seed")
    j = {k: job.get(k) for k in keys}
    j["log"] = job.get("log", [])[-6:]
    j["now"] = time.time()
    return j


def history(limit=60):
    runs = []
    if not OUTPUT_ROOT.is_dir():
        return runs
    for meta_path in OUTPUT_ROOT.glob("*/*/*/Metadata.json"):
        try:
            m = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if m.get("app") != "refstudio" or m.get("status") != "done":
            continue
        d = meta_path.parent
        runs.append({
            "folder": d.relative_to(OUTPUT_ROOT).as_posix(),
            "label": m.get("title"), "prompt": m.get("user_prompt"),
            "shape": m.get("shape"), "steps": m.get("steps"), "guidance": m.get("cfg"),
            "seed": m.get("seed"), "finished": m.get("generation_finished"),
            "seconds_per_image": round(m["generation_seconds"] / max(len(m.get("images") or [1]), 1)),
            "images": [rel_url(d / p["file"]) for p in m.get("images", []) if (d / p["file"]).is_file()],
            "refs": [rel_url(p) for p in sorted((d / "references").glob("*")) if p.is_file()],
        })
    runs.sort(key=lambda r: r["finished"] or "", reverse=True)
    return runs[:limit]


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "RefStudio/1.0"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("Upload too large.")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/status":
            j = JOBS.get(CURRENT["id"]) if CURRENT["id"] else None
            return self._send(200, {"comfy": comfy_up(), "busy": bool(j), "job": public_job(j) if j else None,
                                    "max_refs": MAX_REFS, "documented_refs": DOCUMENTED_REFS,
                                    "shapes": {k: list(v) for k, v in SHAPES.items()},
                                    "ref_budget_mp": REF_BUDGET_MP, "model": FLUX2_UNET})
        if path.startswith("/api/jobs/"):
            j = JOBS.get(path.rsplit("/", 1)[-1])
            return self._send(200, public_job(j)) if j else self._send(404, {"error": "No such job"})
        if path == "/api/history":
            return self._send(200, history())
        if path.startswith("/files/"):
            target = (OUTPUT_ROOT / unquote(path[len("/files/"):])).resolve()
            if OUTPUT_ROOT.resolve() not in target.parents or not target.is_file():
                return self._send(404, {"error": "Not found"})
            ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(
                target.suffix.lower(), "application/octet-stream")
            return self._send(200, target.read_bytes(), ctype)
        return self._send(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._json_body()
        except (ValueError, json.JSONDecodeError) as e:
            return self._send(400, {"error": str(e)})
        if path == "/api/generate":
            try:
                job = start_job(body)
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except RuntimeError as e:
                return self._send(409, {"error": str(e)})
            return self._send(200, public_job(job))
        if path == "/api/cancel":
            j = JOBS.get(CURRENT["id"]) if CURRENT["id"] else None
            if not j:
                return self._send(200, {"ok": True})
            j["cancel"] = True
            try:
                requests.post(f"{COMFY}/interrupt", timeout=5)
            except requests.RequestException:
                pass
            return self._send(200, {"ok": True})
        if path == "/api/reveal":
            target = (OUTPUT_ROOT / str(body.get("folder", ""))).resolve()
            if OUTPUT_ROOT.resolve() in target.parents and target.is_dir():
                subprocess.run(["open", str(target)], capture_output=True)
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "Not found"})
        return self._send(404, {"error": "Not found"})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"{now()}  RefStudio running at {url}  (Ctrl-C to stop)", flush=True)
    print(f"{now()}  Output: {OUTPUT_ROOT}   ComfyUI: {COMFY}   Model: {FLUX2_UNET}", flush=True)
    if not os.environ.get("REFSTUDIO_NO_BROWSER"):
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    sys.exit(main())
