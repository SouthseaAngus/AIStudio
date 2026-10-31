"""Regenerate documentation/Image Types.md from styles.types in config.yaml.

Each type is illustrated with a real image from your Output folder, chosen in
this order:
  1. the run named by the type's optional `example_image` in config.yaml
  2. the latest run of the type's `example` request (preferring one that used this type)
  3. the latest run of any request that used this type
A run is used for one type only. The chosen image is copied (downsized) into
documentation/images/ so the document works anywhere, including GitHub, and the
document shows the request and the prompt that actually produced it.

Usage (from anywhere):
    python tools/gen_image_types_doc.py                     # rebuild the document
    python tools/gen_image_types_doc.py --generate-missing  # first run the example
                                                            # request for types with no image
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

DOC = Path("documentation/Image Types.md")
IMG_DIR = Path("documentation/images")
IMG_EDGE = 1024  # long edge of the copies kept with the document

FAMILY_NAMES = {"photo": "Photographic", "graphic": "Graphic", "art": "Art and illustration"}
FAMILY_RULES = {
    "photo": "Photographic language welcome: light, lens, depth of field.",
    "graphic": "No photographic language at all; named colours are honoured; fixed backgrounds where set.",
    "art": "Describe medium and technique; no photographic language.",
}


# ---------------------------------------------------------------- runs

def load_runs(output_root):
    """Every finished run under Output/, newest first."""
    runs = []
    for meta_path in output_root.glob("*/*/*/Metadata.json"):
        folder = meta_path.parent
        images = sorted(folder.glob("Image_*.png")) or sorted(folder.glob("*.png")) or sorted(folder.glob("*.jpg"))
        if not images:
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        spec = {}
        if (folder / "Prompt.json").is_file():
            try:
                spec = json.loads((folder / "Prompt.json").read_text())
            except json.JSONDecodeError:
                pass
        runs.append({
            "folder": folder,
            "rel": folder.relative_to(output_root).as_posix(),
            "image": images[0],
            "style": meta.get("style") or spec.get("style"),
            "request": meta.get("user_prompt", ""),
            "positive": meta.get("positive") or spec.get("positive", ""),
            "text": meta.get("text") or spec.get("text", ""),
            "model": meta.get("model_capability", ""),
            "steps": meta.get("steps"),
            "seed": meta.get("seed"),
            "seconds": meta.get("generation_seconds"),
            "finished": meta.get("generation_finished") or "",
        })
    runs.sort(key=lambda r: (r["finished"], r["rel"]), reverse=True)
    return runs


def norm(s):
    return " ".join(str(s).lower().split())


def choose_examples(types, runs, output_root):
    chosen, used = {}, set()

    def take(name, run):
        chosen[name] = run
        used.add(run["rel"])

    # 1. pinned in config
    for name, st in types.items():
        pin = st.get("example_image")
        if not pin:
            continue
        match = [r for r in runs if r["rel"] == pin.strip("/")]
        if match:
            take(name, match[0])
        else:
            print(f"WARN: {name}.example_image '{pin}' not found under {output_root}")

    # 2. latest run of the type's example request
    for name, st in types.items():
        if name in chosen:
            continue
        same = [r for r in runs if norm(r["request"]) == norm(st["example"]) and r["rel"] not in used]
        same.sort(key=lambda r: r["style"] == name, reverse=True)  # stable: newest within each group
        if same:
            take(name, same[0])

    # 3. latest unused run that used the type
    for name in types:
        if name in chosen:
            continue
        for r in runs:
            if r["style"] == name and r["rel"] not in used:
                take(name, r)
                break
    return chosen


def copy_image(src, dest_stem):
    """Downsized JPEG copy for the document (sips on macOS, else Pillow, else a plain copy)."""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    jpg = IMG_DIR / f"{dest_stem}.jpg"
    if jpg.is_file() and jpg.stat().st_mtime >= src.stat().st_mtime:
        return jpg
    if shutil.which("sips"):
        r = subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85",
                            "-Z", str(IMG_EDGE), str(src), "--out", str(jpg)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return jpg
    try:
        from PIL import Image
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((IMG_EDGE, IMG_EDGE))
            im.save(jpg, "JPEG", quality=85)
        return jpg
    except ImportError:
        dest = IMG_DIR / f"{dest_stem}{src.suffix.lower()}"
        shutil.copy2(src, dest)
        return dest


def generate_missing(types, chosen):
    missing = [n for n in types if n not in chosen]
    if not missing:
        print("Every type already has an example image.")
        return
    for name in missing:
        req = types[name]["example"]
        print(f"Generating example for {name}: {req}")
        r = subprocess.run([sys.executable, "controller.py", req, "--style", name])
        if r.returncode != 0:
            print(f"WARN: generation for {name} failed (exit {r.returncode})")


# ---------------------------------------------------------------- document

def md_path(p):
    return p.relative_to(DOC.parent).as_posix().replace(" ", "%20")


def build(cfg, types, dims, chosen, output_root):
    text_cfg = cfg["styles"].get("text", {})
    L = []
    w = L.append
    w("# AIStudio Image Types\n")
    w(f"AIStudio can produce **{len(types)} types of image**. Each type is defined once, in the "
      "`styles.types` section of `config.yaml`, and that one definition drives everything: the "
      "catalogue the orchestrator LLM chooses from, how it writes the prompt, the shape and model "
      "used, the FLUX guidance, the negative prompt and the safety checks applied afterwards.\n")
    w("This document is generated from `config.yaml`, and every example image is a real AIStudio "
      "run from your Output folder, shown with the request and the prompt that produced it. "
      "Regenerate it after changing a type or making better examples (see *Keeping this document "
      "current* at the end).\n")

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

    w("## Words in the image\n")
    w("Any type can carry words: a poster title, a logo's name, a sign. Ask for them and put the "
      "exact words in quotes:\n")
    w("```zsh\npython controller.py 'a railway poster for Southsea seafront titled \"SOUTHSEA\"'\n"
      "python controller.py 'a logo for my studio reading \"Angus Photo\"'\n```\n")
    w("The orchestrator copies the words into a `text` field and writes them into the prompt in "
      "quotes, with their style and position. AIStudio then makes sure they can be read:\n")
    if text_cfg:
        w(f"- the run switches to `{text_cfg.get('model')}`, because FLUX Schnell can't spell;")
        w(f"- guidance is raised to at least {text_cfg.get('guidance')}, so FLUX sticks to the wording;")
        w("- \"text\", \"lettering\" and similar are removed from the negative prompt;")
        w(f"- anything over {text_cfg.get('max_length')} characters is allowed but warned about: "
          "short wording, a word or two, renders most reliably.\n")
    w("Without quoted words FLUX may still invent some lettering, and invented lettering is "
      "usually gibberish. Settings are in `styles.text` in `config.yaml`; the words used are "
      "recorded in each run's `Metadata.json`.\n")

    w("## The three families\n")
    w("Every type belongs to a family, which sets the vocabulary the LLM is allowed to use:\n")
    w("| Family | Types | Rule |\n|---|---|---|")
    for fam in ("photo", "graphic", "art"):
        names = ", ".join(f"`{n}`" for n, s in types.items() if s["family"] == fam)
        w(f"| {FAMILY_NAMES[fam]} | {names} | {FAMILY_RULES[fam]} |")
    w("")

    w("## Quick reference\n")
    w("| Type | Produces | Shape | Model | Guidance |\n|---|---|---|---|---|")
    for n, s in types.items():
        wd, ht = dims[s["workflow"]]
        lock = " (fixed)" if s.get("lock_workflow") else ""
        w(f"| [`{n}`](#{n}) | {s['description']} | {s['workflow']}{lock}, {wd}x{ht} | {s['model']} | {s['cfg']} |")
    w("")
    w("Shape is the default workflow and its canvas size; the LLM may adjust the size to suit the "
      "content. Models `photorealistic` and `highest_quality` are FLUX Dev; `fast_preview` is FLUX "
      "Schnell (capped at 4 steps).\n")

    current = None
    for n, s in types.items():
        if s["family"] != current:
            current = s["family"]
            w(f"## {FAMILY_NAMES[current]} types\n")
        wd, ht = dims[s["workflow"]]
        w(f"### `{n}`\n")
        w(f"**{s['description']}.** Chosen when: {s['choose_when']}.\n")
        w("| Setting | Value |\n|---|---|")
        w(f"| Workflow | `{s['workflow']}` ({wd}x{ht}){', fixed' if s.get('lock_workflow') else ''} |")
        w(f"| Model | `{s['model']}` |")
        w(f"| FLUX guidance | {s['cfg']} |")
        if s.get("background"):
            w(f"| Background | {s['background']}, unless you name one |")
        w(f"| Always avoided | {s['avoid']} |")
        w("")
        w(f"**Prompt pattern** (X is your subject):\n\n> {s['prompt']}\n")

        run = chosen.get(n)
        if run:
            img = copy_image(run["image"], n)
            w("**Example**\n")
            w(f"```zsh\npython controller.py {json.dumps(run['request'])}\n```\n")
            w(f"![{n} example: {run['request']}]({md_path(img)})\n")
            facts = [f"`{run['model']}`"]
            if run["steps"]:
                facts.append(f"{run['steps']} steps")
            if run["seed"] is not None:
                facts.append(f"seed {run['seed']}")
            if run["seconds"]:
                facts.append(f"{run['seconds']:.0f} s")
            if run["style"] and run["style"] != n:
                facts.append(f"orchestrator chose `{run['style']}`")
            w(f"<sub>{' · '.join(facts)} · Output/{run['rel']}</sub>\n")
            if run["text"]:
                w(f"Words requested: **\"{run['text']}\"**\n")
            w(f"Prompt the orchestrator wrote:\n\n> {run['positive']}\n")
        else:
            w("**Example**\n")
            w(f"```zsh\npython controller.py {json.dumps(s['example'])} --style {n}\n```\n")
            w("*No example generated yet. Run the command above, or "
              "`python tools/gen_image_types_doc.py --generate-missing`, then regenerate.*\n")

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
        ("example", "A typical request, shown by `--list-styles` and used to find or make the example image"),
        ("example_image", "Optional. Pin this document's example to a run folder, relative to "
                          "`Output/`, e.g. `2026/10/2026-10-28 Southsea Seafront Railway Poster`"),
    ]:
        w(f"| `{f}` | {m} |")
    w("")
    w("Test a new type with a dry run, which shows the orchestrator's spec without generating:\n")
    w("```zsh\npython controller.py \"your test request\" --style newtype --dry-run\n```\n")

    w("## Keeping this document current\n")
    w("```zsh\npython tools/gen_image_types_doc.py                     # rebuild\n"
      "python tools/gen_image_types_doc.py --generate-missing  # make missing examples first\n```\n")
    w("Without a pin, each type shows the latest run of its `example` request, or else the latest "
      "run that used the type. To show a particular image, set `example_image`. Example images are "
      "copied to `documentation/images/` at up to "
      f"{IMG_EDGE} px, so commit that folder along with the document.\n")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--generate-missing", action="store_true",
                    help="run each missing type's example request before building")
    a = ap.parse_args()

    cfg = yaml.safe_load(open("config.yaml"))
    types = cfg["styles"]["types"]
    output_root = Path(cfg["output"]["root"]).expanduser()
    dims = {}
    for k, name in cfg["workflows"]["map"].items():
        g = json.load(open(f"workflows/{name}.json"))
        for node in g.values():
            if node["class_type"] in ("EmptySD3LatentImage", "EmptyLatentImage"):
                dims[k] = (node["inputs"]["width"], node["inputs"]["height"])

    chosen = choose_examples(types, load_runs(output_root), output_root)
    if a.generate_missing:
        generate_missing(types, chosen)
        chosen = choose_examples(types, load_runs(output_root), output_root)

    DOC.parent.mkdir(exist_ok=True)
    DOC.write_text(build(cfg, types, dims, chosen, output_root))
    have = [n for n in types if n in chosen]
    missing = [n for n in types if n not in chosen]
    print(f"Wrote {DOC} with {len(have)}/{len(types)} example images.")
    for n in have:
        print(f"  {n:15} {chosen[n]['rel']}")
    if missing:
        print("No example yet for: " + ", ".join(missing))


if __name__ == "__main__":
    main()
