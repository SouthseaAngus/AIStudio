# AIStudio v0.1

Local AI image generation: one-line prompt → Ollama orchestration → ComfyUI
generation → dated, reproducible output folders.

```
Prompt received → Ollama completed → Workflow loaded → Generation started
→ Generation finished → Saved N image(s)
```

## What's where

```
controller.py  config.yaml   the image pipeline and its settings
modules/       shared code (config, logging, Ollama, ComfyUI, output folders)
workflows/     ComfyUI workflow graphs
apps/
  refstudio/   browser app: generate from reference photos (apps/refstudio/README.md)
  scenes/      Key Scenes: a film's key scenes, with stills and clips (apps/scenes/README.md)
  psagent/     a local LLM drives Photoshop
  photoscan/   turn overlapping photos into a 3D model (apps/photoscan/README.md)
tests/         Spinnaker reference tests (tests/README.md)
tools/         gen_image_types_doc.py (rebuilds docs/Image Types.md); make_button.py (Stream Deck keys)
docs/          documentation
Output/        everything generated, in dated run folders (not in git)
```

Run everything from `~/AIStudio` with the venv active, e.g. `python apps/scenes/scenes.py ...`.

## Setup checklist

Work through these in order. Steps 1–4 are one-off.

### 1. Python environment

```zsh
cd ~/AIStudio
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. ComfyUI

If not already installed:

```zsh
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Then open http://127.0.0.1:8188 to confirm it's up.

**Custom nodes: none are required for v0.1.** The bundled workflows use only
core ComfyUI nodes (CheckpointLoaderSimple, CLIPTextEncode, FluxGuidance,
EmptySD3LatentImage, KSampler, VAEDecode, SaveImage) — this is deliberate, so
there is nothing extra to version-pin or break on update. The one add-on worth
installing anyway is **ComfyUI-Manager** (github.com/ltdrdata/ComfyUI-Manager,
cloned into `ComfyUI/custom_nodes/`), which manages any custom nodes you adopt
later for upscaling or LoRA phases.

### 3. Model weights

The workflows expect a single-file fp8 FLUX checkpoint in
`ComfyUI/models/checkpoints/`:

- `flux1-dev-fp8.safetensors` — the Comfy-Org single-file repackage of
  FLUX.1 Dev on Hugging Face (search "Comfy-Org flux1-dev fp8"). The
  single-file version bundles the UNet, CLIP and VAE, which is what lets the
  workflow use plain CheckpointLoaderSimple.
- Optionally `flux1-schnell-fp8.safetensors` for the `fast_preview`
  capability (4-step generations, much quicker on the M4 Pro).

If you install different checkpoints, update `models.map` in `config.yaml` —
that's the whole point of the capability mapping: no code changes.

### 4. Ollama

Already running locally. Set `ollama.orchestrator_model` in `config.yaml` to
your chosen orchestrator (see below), then verify:

```zsh
python controller.py "A red kite over Southsea Castle at sunrise" --dry-run
```

Dry-run performs orchestration only and prints the JSON spec — the fastest
way to compare candidate models for schema discipline.

### 5. First generation

```zsh
python controller.py "A red kite flying over Southsea Castle at sunrise in dramatic cinematic lighting"
```

Output lands in `~/AIStudio/Output/YYYY/MM/YYYY-MM-DD Title/` with
Image_NN.png, Prompt.json, Workflow.json, Metadata.json and Generation.log.

## Choosing the orchestrator model

Requirements for the job: local (reproducibility — a cloud-routed model can't
be pinned in Metadata.json), fast, and reliable at emitting strict JSON at
temperature 0. From your installed set:

- **qwen3.6** or **gemma4:26b** — the sensible candidates. Test both with
  `--dry-run` on a handful of varied prompts and keep whichever follows the
  schema without stray prose. The 26B model will be slower to first token on
  the M4 Pro; if the smaller model is schema-reliable, prefer it — the
  orchestration task is routing and prompt-writing, not deep reasoning.
- **qwen2.5vl:7b** — reserve for Phase 8 (image critique); vision models are
  not the best pure-text instruction followers.
- **nemotron-3-super:cloud** — excluded: cloud-routed, so not pinnable or
  offline-safe.
- **mixtral** — large memory footprint alongside FLUX; no advantage here.

Switching is one line in `config.yaml`.

## Image types

The orchestrator chooses from 20 image types (photographic, graphic, and art
and illustration), defined in `styles.types` in `config.yaml`. Each type sets
its prompt pattern, shape, model, guidance and negative prompt. See
[docs/Image Types.md](docs/Image%20Types.md) for every type
with an example, and how to add your own.

```
python controller.py --list-styles
python controller.py "a heron at Langstone Harbour" --style watercolour
```

## Using your own workflows

Any ComfyUI graph can be dropped in:

1. In ComfyUI settings, enable **Dev Mode**.
2. Build/tune the graph in the UI, then **Save (API format)**.
3. Title the two text nodes **Positive Prompt** and **Negative Prompt**.
4. Save the file into `workflows/` and add it to `workflows.map` in
   `config.yaml`.

The controller injects prompt text, seed, steps, guidance, dimensions and
checkpoint by node title/class, so your graph's internals are otherwise
untouched. Workflow.json in each run folder is the *resolved* graph — the
exact thing ComfyUI executed — so any image can be regenerated by
resubmitting it with the recorded seed.

## CLI reference

```
python controller.py "prompt"                  # full run
python controller.py "prompt" --dry-run        # orchestration only
python controller.py "prompt" --workflow portrait
python controller.py "prompt" --model fast_preview
python controller.py "prompt" --style watercolour   # force an image type
python controller.py --list-styles               # list image types
python controller.py "prompt" --seed 12345     # reproducible
python controller.py "prompt" --count 3        # batch of 3
```

## Roadmap position

This is v0.1 plus most of v0.3 (metadata, logging, organised output came
almost free). Not yet implemented: LoRA injection (the orchestrator schema
omits `lora` for now), automatic workflow selection is in but Stream Deck
integration (v0.4), vision critique (v0.5) and the SQLite prompt-memory
database (v1.0) are next.
