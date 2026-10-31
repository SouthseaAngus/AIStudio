#!/usr/bin/env python3
"""Reference-image tests for AIStudio: show FLUX what something really looks like.

Three methods, each run straight against ComfyUI:

  img2img     Start from your photo instead of pure noise. --denoise sets how far
              FLUX may depart from it (0.3 = relight, 0.8 = reinvent).
  controlnet  Extract the photo's edges and make FLUX follow them while it
              paints everything else from the prompt. Needs the FLUX.1 ControlNet
              Union Pro 2.0 model in ComfyUI/models/controlnet/.
  flux2       FLUX.2 [dev] with one or more reference photos: it builds a new
              scene containing the subject. Needs the three FLUX.2 model files.

Every value given as a list (--denoise, --strength) is swept with the same seed,
so the results compare like for like.

Examples:
  python reference_tests.py img2img --image photos/harbour.jpg \\
      --prompt "..." --denoise 0.45 0.6 0.75
  python reference_tests.py controlnet --image photos/harbour.jpg \\
      --prompt "..." --strength 0.5 0.7 0.9
  python reference_tests.py flux2 --image photos/harbour.jpg --image photos/closeup.jpg \\
      --prompt "..." --size 1536x1024
  python reference_tests.py img2img ... --print-graph     # show the graph, run nothing

Output: ~/AIStudio/Output/YYYY/MM/YYYY-MM-DD Reference Tests/, plus tests.jsonl
recording every setting.
"""

import argparse
import copy
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

HOST = "http://127.0.0.1:8188"
LAUNCHD_LABEL = "com.angus.aistudio.comfyui"
OUTPUT_ROOT = Path("~/AIStudio/Output").expanduser()

FLUX1_CKPT = "flux1-dev-fp8.safetensors"
CONTROLNET = "flux1-dev-controlnet-union-pro-2.safetensors"
FLUX2_UNET = "flux2-dev-Q6_K.gguf"  # GGUF: Apple GPUs have no fp8 support
FLUX2_TE = "mistral_3_small_flux2_bf16.safetensors"
FLUX2_VAE = "flux2-vae.safetensors"

# Where each model belongs, for the error message if it's missing.
MODEL_HOMES = {
    FLUX1_CKPT: "ComfyUI/models/checkpoints/",
    CONTROLNET: "ComfyUI/models/controlnet/",
    FLUX2_UNET: "ComfyUI/models/diffusion_models/",
    FLUX2_TE: "ComfyUI/models/text_encoders/",
    FLUX2_VAE: "ComfyUI/models/vae/",
}


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}", flush=True)


def fail(msg):
    log(f"ERROR: {msg}")
    sys.exit(1)


# ---------------------------------------------------------------- graphs
# API-format graphs. Image inputs are filled with the uploaded file names.

def _flux1_base(prompt, guidance):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": FLUX1_CKPT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]}},
        "4": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["2", 0], "guidance": guidance}},
    }


def _load_scaled(node_id, image_name, megapixels):
    """LoadImage -> scale to ~N megapixels on a 16 px grid."""
    return {
        node_id: {"class_type": "LoadImage", "inputs": {"image": image_name}},
        f"{node_id}s": {"class_type": "ImageScaleToTotalPixels", "inputs": {
            "image": [node_id, 0], "upscale_method": "lanczos",
            "megapixels": megapixels, "resolution_steps": 16}},
    }


def graph_img2img(images, prompt, seed, steps, guidance, megapixels, denoise, prefix, **_):
    g = _flux1_base(prompt, guidance)
    g.update(_load_scaled("10", images[0], megapixels))
    g.update({
        "12": {"class_type": "VAEEncode", "inputs": {"pixels": ["10s", 0], "vae": ["1", 2]}},
        "6": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "positive": ["4", 0], "negative": ["3", 0],
            "latent_image": ["12", 0], "denoise": denoise}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
    })
    return g


def graph_controlnet(images, prompt, seed, steps, guidance, megapixels, strength,
                     end, canny_low, canny_high, init, prefix, **_):
    g = _flux1_base(prompt, guidance)
    g.update(_load_scaled("10", images[0], megapixels))
    g.update({
        "11": {"class_type": "Canny", "inputs": {
            "image": ["10s", 0], "low_threshold": canny_low, "high_threshold": canny_high}},
        "13": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": CONTROLNET}},
        "14": {"class_type": "ControlNetApplyAdvanced", "inputs": {
            "positive": ["4", 0], "negative": ["3", 0], "control_net": ["13", 0],
            "image": ["11", 0], "strength": strength,
            "start_percent": 0.0, "end_percent": end, "vae": ["1", 2]}},
        # At --init 1.0 the encoded photo only sets the size and the edges do
        # all the guiding. Below 1.0 the photo's colours and layout seed the
        # result too (ControlNet + img2img), keeping the scene closer to it.
        "12": {"class_type": "VAEEncode", "inputs": {"pixels": ["10s", 0], "vae": ["1", 2]}},
        "6": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "seed": seed, "steps": steps, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "positive": ["14", 0], "negative": ["14", 1],
            "latent_image": ["12", 0], "denoise": init}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": prefix + "_edges"}},
    })
    return g


def graph_flux2(images, prompt, seed, steps, guidance, megapixels, width, height, prefix, unet=FLUX2_UNET, **_):
    g = {
        "1": ({"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": unet}}
              if unet.endswith(".gguf") else
              {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}}),
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": FLUX2_TE, "type": "flux2"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": FLUX2_VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
    }
    cond = ["4", 0]
    for i, name in enumerate(images):
        nid = f"2{i}"
        g.update(_load_scaled(nid, name, megapixels))
        g[f"{nid}e"] = {"class_type": "VAEEncode", "inputs": {"pixels": [f"{nid}s", 0], "vae": ["3", 0]}}
        g[f"{nid}r"] = {"class_type": "ReferenceLatent", "inputs": {
            "conditioning": cond, "latent": [f"{nid}e", 0]}}
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


BUILDERS = {"img2img": graph_img2img, "controlnet": graph_controlnet, "flux2": graph_flux2}


# ---------------------------------------------------------------- ComfyUI

def _up():
    try:
        return requests.get(f"{HOST}/system_stats", timeout=5).ok
    except requests.RequestException:
        return False


def ensure_comfyui():
    if _up():
        return
    target = f"gui/{os.getuid()}/{LAUNCHD_LABEL}"
    subprocess.run(["launchctl", "kickstart", target], capture_output=True)
    log("Waiting for ComfyUI (up to 120s)")
    deadline = time.time() + 120
    while time.time() < deadline:
        time.sleep(2)
        if _up():
            log("ComfyUI ready")
            return
    fail(f"ComfyUI is not answering at {HOST}. Start it and try again.")


def _combo_options(spec):
    """Option list from an /object_info input spec, old or new format."""
    if isinstance(spec, list) and spec:
        if isinstance(spec[0], list):
            return spec[0]
        if spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
            return spec[1].get("options")
    return None


def preflight(graph, info):
    """Fail loud on missing nodes or models; drop inputs this ComfyUI doesn't know."""
    for nid, node in graph.items():
        cls = node["class_type"]
        if cls not in info:
            if cls == "UnetLoaderGGUF":
                fail("the ComfyUI-GGUF custom node isn't installed, or ComfyUI wasn't restarted after installing it.")
            fail(f"this ComfyUI has no '{cls}' node. Update ComfyUI (git pull) and retry.")
        spec = info[cls]["input"]
        required = spec.get("required", {})
        known = {**required, **spec.get("optional", {})}
        for name in list(node["inputs"]):
            if name not in known:
                del node["inputs"][name]  # older/newer ComfyUI without this input
        for name, s in required.items():
            if name not in node["inputs"]:
                fail(f"node {nid} ({cls}) needs input '{name}', which this script doesn't set")
            opts = _combo_options(s)
            val = node["inputs"][name]
            if opts is not None and isinstance(val, str) and val not in opts:
                if val in MODEL_HOMES or name == "unet_name":
                    fail(f"model '{val}' not found. Put it in {MODEL_HOMES.get(val, 'ComfyUI/models/diffusion_models/')} "
                         f"and restart ComfyUI.")
                if cls != "LoadImage":
                    fail(f"{cls}.{name} = '{val}' is not an option here: {opts[:8]}")


def upload(path):
    with open(path, "rb") as f:
        r = requests.post(f"{HOST}/upload/image",
                          files={"image": (path.name, f)}, data={"overwrite": "true"}, timeout=60)
    if not r.ok:
        fail(f"upload of {path} failed: HTTP {r.status_code} {r.text}")
    j = r.json()
    return f"{j['subfolder']}/{j['name']}" if j.get("subfolder") else j["name"]


def run(graph):
    r = requests.post(f"{HOST}/prompt", json={"prompt": graph, "client_id": "reference-tests"}, timeout=60)
    if r.status_code != 200:
        fail(f"ComfyUI rejected the graph (HTTP {r.status_code}): {r.text}")
    pid = r.json()["prompt_id"]
    start = time.time()
    while True:
        time.sleep(3)
        if time.time() - start > 7200:
            fail(f"timed out after 2 hours (prompt {pid})")
        h = requests.get(f"{HOST}/history/{pid}", timeout=30).json()
        if pid in h:
            status = h[pid].get("status", {})
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                fail(f"ComfyUI error: {json.dumps(msgs[-1][1] if msgs else status)[:1500]}")
            if h[pid].get("outputs"):
                return h[pid]["outputs"]


def fetch(outputs):
    files = []
    for out in outputs.values():
        for img in out.get("images", []):
            if img.get("type") != "output":
                continue
            r = requests.get(f"{HOST}/view", params={
                "filename": img["filename"], "subfolder": img.get("subfolder", ""),
                "type": "output"}, timeout=120)
            r.raise_for_status()
            files.append((img["filename"], r.content))
    return files


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("method", choices=BUILDERS)
    p.add_argument("--image", action="append", required=True, type=Path,
                   help="reference photo (repeat for several with flux2)")
    p.add_argument("--prompt", required=True)
    p.add_argument("--label", default="test", help="short name used in the output file names")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--steps", type=int, default=None, help="default 30 (FLUX.1) or 28 (FLUX.2)")
    p.add_argument("--guidance", type=float, default=None, help="default 3.5 (FLUX.1) or 4.0 (FLUX.2)")
    p.add_argument("--megapixels", type=float, default=1.0, help="reference image size")
    p.add_argument("--denoise", type=float, nargs="+", default=[0.6], help="img2img: 0.3-0.9")
    p.add_argument("--strength", type=float, nargs="+", default=[0.7], help="controlnet: 0.4-1.0")
    p.add_argument("--end", type=float, default=0.8, help="controlnet: stop following edges at this fraction")
    p.add_argument("--init", type=float, nargs="+", default=[1.0],
                   help="controlnet: below 1.0 also starts from the photo (0.85-0.95 keeps the scene)")
    p.add_argument("--canny", type=float, nargs=2, default=[0.4, 0.8], metavar=("LOW", "HIGH"))
    p.add_argument("--size", default="1536x1024", help="flux2 output size, WxH")
    p.add_argument("--unet", default=FLUX2_UNET, help="flux2 model file in models/diffusion_models (.gguf or .safetensors)")
    p.add_argument("--print-graph", action="store_true", help="print the graph and exit")
    a = p.parse_args()

    for img in a.image:
        if not img.is_file():
            fail(f"image not found: {img}")
    if a.method != "flux2" and len(a.image) > 1:
        log(f"NOTE: {a.method} uses only the first image")
    flux2 = a.method == "flux2"
    steps = a.steps or (28 if flux2 else 30)
    guidance = a.guidance if a.guidance is not None else (4.0 if flux2 else 3.5)
    seed = a.seed if a.seed is not None else random.randint(0, 2**32 - 1)
    try:
        width, height = (int(v) for v in a.size.lower().split("x"))
    except ValueError:
        fail("--size must look like 1536x1024")
    width, height = width // 16 * 16, height // 16 * 16

    if a.method == "img2img":
        sweep = [{"denoise": v} for v in a.denoise]
    elif a.method == "controlnet":
        sweep = [{"strength": s, "init": i} for i in a.init for s in a.strength]
    else:
        sweep = [{}]

    base = dict(prompt=a.prompt, seed=seed, steps=steps, guidance=guidance,
                megapixels=a.megapixels, end=a.end, canny_low=a.canny[0],
                canny_high=a.canny[1], width=width, height=height, unet=a.unet)

    if a.print_graph:
        names = [i.name for i in a.image]
        for sw in sweep:
            params = {**base, **sw}
            print(json.dumps(BUILDERS[a.method](names, prefix="preview", **params), indent=2))
        return

    ensure_comfyui()
    info = requests.get(f"{HOST}/object_info", timeout=60).json()
    names = [upload(i) for i in a.image]
    log(f"Uploaded {len(names)} reference image(s)")

    now = datetime.now()
    out_dir = OUTPUT_ROOT / f"{now:%Y}" / f"{now:%m}" / f"{now:%Y-%m-%d} Reference Tests"
    out_dir.mkdir(parents=True, exist_ok=True)

    for sw in sweep:
        bits = [f"{k}{v:.2f}" for k, v in sw.items() if not (k == "init" and v == 1.0)]
        tag = "_".join([a.method, a.label, *bits, str(seed)])
        params = {**base, **sw}
        graph = BUILDERS[a.method](names, prefix=f"reftest/{tag}", **params)
        preflight(graph, info)
        log(f"Running {tag}")
        t0 = time.time()
        files = fetch(run(copy.deepcopy(graph)))
        secs = round(time.time() - t0, 1)
        saved = []
        for fname, data in files:
            suffix = "_edges" if "_edges" in fname else ""
            dest = out_dir / f"{tag}{suffix}.png"
            dest.write_bytes(data)
            saved.append(dest.name)
        with (out_dir / "tests.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "time": datetime.now().isoformat(timespec="seconds"), "method": a.method,
                "label": a.label, "images": [str(i) for i in a.image], "seconds": secs,
                "files": saved, **params}) + "\n")
        log(f"Done in {secs}s -> {', '.join(saved)}")

    log(f"Results in {out_dir}")


if __name__ == "__main__":
    main()
