"""Regenerate documentation/Image Types.md from styles.types in config.yaml.

Usage (from anywhere):  python tools/gen_image_types_doc.py
"""
import json
import os
from pathlib import Path

import yaml

os.chdir(Path(__file__).resolve().parent.parent)  # repo root

cfg = yaml.safe_load(open("config.yaml"))
types = cfg["styles"]["types"]
dims = {}
for k, name in cfg["workflows"]["map"].items():
    g = json.load(open(f"workflows/{name}.json"))
    for n in g.values():
        if n["class_type"] in ("EmptySD3LatentImage", "EmptyLatentImage"):
            dims[k] = (n["inputs"]["width"], n["inputs"]["height"])

subject = {
    "photo": "a red kite flying over Southsea Castle at sunrise",
    "portrait": "an elderly fisherman mending nets on Hayling Island, weathered face, wool jumper",
    "landscape": "the Isle of Wight seen from Southsea beach at dusk, shingle in the foreground",
    "macro": "a dewdrop on a spider's web, the garden reflected upside down inside it",
    "product": "a brown leather camera strap, coiled",
    "architecture": "the Spinnaker Tower from Gunwharf Quays at blue hour",
    "monochrome": "a rainy Portsmouth street at night, reflections on wet cobbles",
    "cinematic": "a lone lighthouse keeper climbing a spiral staircase during a storm",
    "clipart": "a cheerful yellow frog",
    "logo": "a camera aperture merging into a breaking wave",
    "icon": "a play button inside a node-graph symbol",
    "pixel_art": "a Portsmouth to Isle of Wight car ferry",
    "vintage_poster": "Southsea seafront with the pier, beach huts and a paddle steamer",
    "illustration": "a fox reading a map in an autumn forest",
    "watercolour": "a grey heron standing in the shallows at Langstone Harbour",
    "oil_painting": "HMS Victory in dry dock",
    "pencil_sketch": "an old Leica rangefinder camera",
    "line_art": "a seahorse among seaweed",
    "storybook": "a hedgehog sailing a teacup across a pond",
    "3d_render": "a tiny photography studio with lights and a backdrop",
}
assert set(subject) == set(types), set(types) ^ set(subject)

fam_names = {"photo": "Photographic", "graphic": "Graphic", "art": "Art and illustration"}
L = []
w = L.append
w("# AIStudio Image Types\n")
w(f"AIStudio can produce **{len(types)} types of image**. Each type is defined once, in the "
  "`styles.types` section of `config.yaml`, and that one definition drives everything: the "
  "catalogue the orchestrator LLM chooses from, how it writes the prompt, the shape and model "
  "used, the FLUX guidance, the negative prompt and the safety checks applied afterwards.\n")
w("This document is generated from `config.yaml`. If you change a type there, regenerate it "
  "(see *Keeping this document current* at the end).\n")

w("## Choosing a type\n")
w("You normally don't need to. The orchestrator reads your request and picks the type whose "
  "trigger words match best; the most specific match wins, and a medium you name always beats "
  "the subject (\"a portrait in watercolour\" is `watercolour`, not `portrait`). If nothing "
  f"matches, it uses `{cfg['styles']['default']}`.\n")
w("To force a type, or see the list:\n")
w("```zsh\npython controller.py \"a heron at Langstone Harbour\" --style watercolour\n"
  "python controller.py --list-styles\n```\n")
w("`--style` tells the LLM which type to write for, so the prompt is written in that type's "
  "language, not just relabelled. `--workflow` and `--model` still override shape and model "
  "afterwards, except that a type with a fixed workflow keeps it.\n")

w("## The three families\n")
w("Every type belongs to a family, which sets the vocabulary the LLM is allowed to use:\n")
w("| Family | Types | Rule |\n|---|---|---|")
rules = {
    "photo": "Photographic language welcome: light, lens, depth of field.",
    "graphic": "No photographic language at all; named colours are honoured; fixed backgrounds where set.",
    "art": "Describe medium and technique; no photographic language.",
}
for fam in ("photo", "graphic", "art"):
    names = ", ".join(f"`{n}`" for n, s in types.items() if s["family"] == fam)
    w(f"| {fam_names[fam]} | {names} | {rules[fam]} |")
w("")

w("## Quick reference\n")
w("| Type | Produces | Shape | Model | Guidance |\n|---|---|---|---|---|")
for n, s in types.items():
    wd, ht = dims[s["workflow"]]
    lock = " (fixed)" if s.get("lock_workflow") else ""
    w(f"| `{n}` | {s['description']} | {s['workflow']}{lock}, {wd}x{ht} | {s['model']} | {s['cfg']} |")
w("")
w("Shape is the default workflow and its canvas size; the LLM may adjust the size to suit the "
  "content. Model `photorealistic` and `highest_quality` are FLUX Dev (about 10 minutes per "
  "image); `fast_preview` is FLUX Schnell (about 20 seconds, capped at 4 steps).\n")

current = None
for n, s in types.items():
    if s["family"] != current:
        current = s["family"]
        w(f"## {fam_names[current]} types\n")
    wd, ht = dims[s["workflow"]]
    w(f"### `{n}`: {s['description']}\n")
    w(f"**Chosen when:** {s['choose_when']}.\n")
    w("| Setting | Value |\n|---|---|")
    w(f"| Workflow | `{s['workflow']}` ({wd}x{ht}){', fixed' if s.get('lock_workflow') else ''} |")
    w(f"| Model | `{s['model']}` |")
    w(f"| FLUX guidance | {s['cfg']} |")
    if s.get("background"):
        w(f"| Background | {s['background']}, unless you name one |")
    w(f"| Always avoided | {s['avoid']} |")
    w("")
    w(f"**Prompt pattern** (X is your subject):\n\n> {s['prompt']}\n")
    pos = s["prompt"].replace("X", subject[n], 1)
    if s.get("background"):
        pos += f" on a {s['background']} background"
    w("**Example**\n")
    w(f"```zsh\npython controller.py \"{s['example']}\"\n```\n")
    w(f"The orchestrator writes a positive prompt along these lines:\n\n> {pos}\n")

w("## Adding or changing a type\n")
w("Add an entry under `styles.types` in `config.yaml`. Every field below is required unless "
  "marked optional; the config loader stops with a clear error if one is missing or invalid.\n")
w("| Field | Meaning |\n|---|---|")
for f, m in [
    ("family", "`photo`, `graphic` or `art`; sets the vocabulary rules"),
    ("description", "One line saying what the type produces"),
    ("choose_when", "Trigger words and situations the LLM matches against"),
    ("prompt", "The positive-prompt pattern, with X standing for the subject"),
    ("avoid", "Always placed at the start of the negative prompt"),
    ("workflow", "Default shape, a key of `workflows.map`"),
    ("lock_workflow", "Optional. `true` stops the LLM or `--workflow` moving it to another shape"),
    ("model", "Default model capability, a key of `models.map`"),
    ("cfg", "FLUX guidance used for every run of this type"),
    ("background", "Optional. The prompt must end \"on a <colour> background\""),
    ("example", "A typical request, shown by `--list-styles`"),
]:
    w(f"| `{f}` | {m} |")
w("")
w("Test a new type with a dry run, which shows the orchestrator's spec without generating:\n")
w("```zsh\npython controller.py \"your test request\" --style newtype --dry-run\n```\n")
w("## Keeping this document current\n")
w("Regenerate it after editing the catalogue:\n")
w("```zsh\npython tools/gen_image_types_doc.py\n```\n")

Path("documentation").mkdir(exist_ok=True)
Path("documentation/Image Types.md").write_text("\n".join(L))
print(len("\n".join(L).split()), "words")
