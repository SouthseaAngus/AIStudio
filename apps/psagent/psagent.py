#!/usr/bin/env python3
"""psagent: a local LLM drives Photoshop.

You give it a photo and a request in plain English. The orchestrator model in
Ollama plans N different versions using a fixed menu of Photoshop techniques
(pslib.jsx), and each version is rendered in Photoshop and saved as a
maximum-quality JPEG.

    python apps/psagent/psagent.py ~/Pictures/heron.jpg \\
        "Isolate the subject, turn it into an ink drawing with wash, turn the background into a graphite pencil drawing"

Options:
    --count 10        number of versions
    --size 3000       working size, long edge in px (0 = original size)
    --dry-run         plan only: print the plan, don't touch Photoshop
    --plan FILE       skip the LLM and re-render a saved Plan.json
    --only 3 7        render only these version numbers

Output: ~/AIStudio/Output/YYYY/MM/YYYY-MM-DD <Title>/ with the JPEGs, Plan.json,
the request, Generation.log and the Photoshop scripts that made each version.
"""

import argparse
import json
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
AISTUDIO = HERE.parent.parent
LIB = HERE / "pslib.jsx"
OUTPUT_ROOT = Path("~/AIStudio/Output").expanduser()

# ---------------------------------------------------------------- catalogue
# (description for the LLM, {param: (min, max) | [choices] | "hex"})

OPS = {
    "keep": ("leave this region as the original photo", {}),
    "ink_lines": ("black ink line drawing on white, no colour", {
        "method": ["edges", "highpass"], "detail": (1, 10), "weight": (0, 4),
        "contrast": (0, 1), "simplify": (0, 8)}),
    "ink_and_wash": ("pen-and-ink lines over a soft, simplified wash of the original colours", {
        "line_method": ["edges", "highpass"], "line_detail": (1, 10), "line_weight": (0, 4),
        "line_contrast": (0, 1), "line_simplify": (0, 8), "line_opacity": (0, 100),
        "wash_colour": (0, 1), "wash_simplify": (1, 12), "wash_softness": (0, 10),
        "wash_lightness": (0, 1)}),
    "watercolour": ("loose watercolour: blended colour with faint edges", {
        "colour": (0, 1), "simplify": (1, 12), "softness": (0, 10), "lightness": (0, 1),
        "edge_opacity": (0, 100)}),
    "graphite_pencil": ("graphite pencil sketch, grey on white", {
        "softness": (1, 40), "darkness": (0, 1), "grain": (0, 20), "hatching": (0, 12),
        "angle": (-90, 90)}),
    "charcoal": ("soft, dark, smudgy charcoal drawing", {
        "softness": (1, 40), "darkness": (0, 1), "grain": (0, 20)}),
    "flat_colour": ("flat poster-like colour areas with optional dark outlines", {
        "levels": (2, 12), "simplify": (1, 12), "outline_opacity": (0, 100)}),
    "monochrome": ("black and white photograph", {"contrast": (0, 1)}),
    "tint": ("wash the region in one colour, e.g. sepia 704214 or blue 2B4C7E", {
        "colour": "hex", "opacity": (0, 100)}),
    "blur": ("soften the region out of focus", {"radius": (0, 30)}),
}

FINISH = {
    "paper": ("lay the whole image on tinted paper with grain", {
        "colour": "hex", "opacity": (0, 100), "grain": (0, 15)}),
    "contrast": ("adjust overall contrast, -1 flatter to +1 punchier", {"amount": (-1, 1)}),
}

PARAM_NOTES = """Parameter guide (pixels are at a 3000 px working size):
- detail / line_detail: 1 fine lines .. 10 broad strokes (highpass only)
- weight / line_weight: extra line thickness in px, 0 thin .. 4 heavy
- contrast / line_contrast: 0 faint, many grey lines .. 1 bold, few lines
- simplify / line_simplify / wash_simplify: how much detail is removed first
- line_opacity, edge_opacity, opacity: 0..100 percent
- wash_colour / colour: 0 grey .. 1 full original colour
- wash_lightness / lightness: 0 rich .. 1 pale, washed-out
- softness: graphite 3 crisp .. 25 very soft; wash 0 crisp .. 10 bleeding
- darkness: 0 light touch .. 1 heavy, dark pencil
- grain: paper and pencil grain, 0 none .. 20 coarse
- hatching: length of directional strokes in px (0 none), at angle degrees
- mask_feather: softness of the subject cut-out edge in px, 0..20"""


def log(msg, logfile=None):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    if logfile:
        with open(logfile, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def fail(msg, logfile=None):
    log(f"ERROR: {msg}", logfile)
    sys.exit(1)


def load_settings():
    """Ollama host and model from AIStudio's config.yaml, if present."""
    s = {"host": "http://127.0.0.1:11434", "model": "gemma4:26b", "num_ctx": 16384}
    cfg = AISTUDIO / "config.yaml"
    if cfg.is_file():
        try:
            import yaml
            c = yaml.safe_load(cfg.read_text())["ollama"]
            s["host"] = c.get("host", s["host"])
            s["model"] = c.get("orchestrator_model", s["model"])
        except Exception:
            pass
    return s


# ---------------------------------------------------------------- planning

def _describe(table):
    out = []
    for name, (desc, params) in table.items():
        ps = []
        for p, spec in params.items():
            if isinstance(spec, tuple):
                ps.append(f"{p} {spec[0]}..{spec[1]}")
            elif isinstance(spec, list):
                ps.append(f"{p} {'|'.join(spec)}")
            else:
                ps.append(f"{p} hex colour")
        out.append(f'- "{name}": {desc}' + (f" [{', '.join(ps)}]" if ps else ""))
    return "\n".join(out)


def system_prompt(count):
    return f"""You plan image edits that a script will carry out in Photoshop.
The user gives a request about their photo. You cannot invent new techniques:
every step must be one of these operations.

Region operations (applied in order to a region):
{_describe(OPS)}

Finishing operations (applied to the whole combined image at the end):
{_describe(FINISH)}

{PARAM_NOTES}

Photoshop's Select Subject can split the photo into the main subject and the
background. Set "isolate_subject" true only if the request treats them
differently; then each version has "subject" and "background" step lists.
Otherwise each version has a single "all" step list.

Make exactly {count} versions. Each must honour the request but be clearly
different from the others: vary line method, weight and contrast, how much
colour the wash keeps, pencil softness, darkness and hatching, the paper tone,
and use the parameter ranges fully. Make two or three bolder interpretations
(for example charcoal instead of graphite, or heavy flat colour) where they
still fit the request.

Respond with ONLY a JSON object:
{{
  "title": "Short Title Case name for the output folder, max 6 words",
  "isolate_subject": true,
  "versions": [
    {{
      "name": "two to four words",
      "idea": "one sentence on what makes this version different",
      "subject": [{{"op": "ink_and_wash", "line_weight": 1.5, "wash_colour": 0.6}}],
      "background": [{{"op": "graphite_pencil", "softness": 10, "darkness": 0.4}}],
      "mask_feather": 2,
      "finish": [{{"op": "paper", "colour": "F3EAD8", "opacity": 50, "grain": 3}}]
    }}
  ]
}}"""


def ask_llm(settings, request, count, seed, logfile):
    payload = {
        "model": settings["model"],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.6, "seed": seed, "num_ctx": settings["num_ctx"]},
        "messages": [
            {"role": "system", "content": system_prompt(count)},
            {"role": "user", "content": request},
        ],
    }
    try:
        r = requests.post(f"{settings['host']}/api/chat", json=payload, timeout=900)
        r.raise_for_status()
    except requests.RequestException as e:
        fail(f"Ollama request failed: {e}", logfile)
    content = r.json().get("message", {}).get("content", "")
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        fail(f"the LLM did not return valid JSON ({e}). Raw output:\n{content[:2000]}", logfile)


def _clean_steps(steps, table, where, warnings):
    if not isinstance(steps, list):
        steps = [steps] if isinstance(steps, dict) else []
    out = []
    for s in steps:
        if not isinstance(s, dict) or s.get("op") not in table:
            warnings.append(f"{where}: dropped unknown step {s!r}")
            continue
        spec = table[s["op"]][1]
        clean = {"op": s["op"]}
        for k, v in s.items():
            if k == "op":
                continue
            if k not in spec:
                warnings.append(f"{where}: {s['op']} has no parameter '{k}', ignored")
                continue
            rule = spec[k]
            if isinstance(rule, tuple):
                try:
                    clean[k] = min(max(float(v), rule[0]), rule[1])
                except (TypeError, ValueError):
                    warnings.append(f"{where}: {s['op']}.{k}={v!r} is not a number, ignored")
            elif isinstance(rule, list):
                if v in rule:
                    clean[k] = v
                else:
                    warnings.append(f"{where}: {s['op']}.{k}={v!r} not one of {rule}, ignored")
            else:
                h = str(v).lstrip("#")
                if re.fullmatch(r"[0-9a-fA-F]{6}", h):
                    clean[k] = h.upper()
                else:
                    warnings.append(f"{where}: {s['op']}.{k}={v!r} is not a hex colour, ignored")
        out.append(clean)
    return out


def validate(plan, count):
    """Keep only known operations and parameters, clamped to their ranges."""
    warnings = []
    if not isinstance(plan, dict) or not isinstance(plan.get("versions"), list):
        raise ValueError("plan has no 'versions' list")
    isolate = bool(plan.get("isolate_subject"))
    title = re.sub(r"[^A-Za-z0-9 \-]", "", str(plan.get("title") or "Photoshop Versions")).strip()
    versions = []
    for i, v in enumerate(plan["versions"][:count], 1):
        if not isinstance(v, dict):
            continue
        where = f"version {i}"
        try:
            feather = min(max(float(v.get("mask_feather", 2) or 0), 0), 20)
        except (TypeError, ValueError):
            feather = 2.0
        clean = {
            "name": re.sub(r"[^A-Za-z0-9 \-]", "", str(v.get("name") or f"Version {i}")).strip()[:40] or f"Version {i}",
            "idea": str(v.get("idea", "")),
            "mask_feather": feather,
            "finish": _clean_steps(v.get("finish", []), FINISH, where, warnings),
        }
        if isolate:
            clean["subject"] = _clean_steps(v.get("subject", []), OPS, where + " subject", warnings) or [{"op": "keep"}]
            clean["background"] = _clean_steps(v.get("background", []), OPS, where + " background", warnings) or [{"op": "keep"}]
        else:
            steps = v.get("all") or v.get("subject") or []
            clean["all"] = _clean_steps(steps, OPS, where, warnings) or [{"op": "keep"}]
        versions.append(clean)
    if len(versions) < count:
        warnings.append(f"the LLM planned {len(versions)} versions instead of {count}")
    if not versions:
        raise ValueError("no usable versions in the plan")
    return {"title": title or "Photoshop Versions", "isolate_subject": isolate, "versions": versions}, warnings


# ---------------------------------------------------------------- Photoshop

APPLESCRIPT = [
    "on run argv",
    "with timeout of 1800 seconds",
    'tell application id "com.adobe.Photoshop" to do javascript (item 1 of argv)',
    "end timeout",
    "end run",
]


def photoshop(js):
    cmd = ["osascript"]
    for line in APPLESCRIPT:
        cmd += ["-e", line]
    r = subprocess.run(cmd + [js], capture_output=True, text=True)
    if r.returncode != 0:
        return f"ERROR: osascript: {r.stderr.strip()}"
    return r.stdout.strip()


def variant_script(src, out, version, isolate, size):
    return (
        "// Generated by psagent: re-run in Photoshop via File > Scripts > Browse.\n"
        f"$.evalFile(new File({json.dumps(str(LIB))}));\n"
        f"psagentRun({json.dumps(str(src))}, {json.dumps(str(out))}, "
        f"{json.dumps(version, indent=1)}, {'true' if isolate else 'false'}, {int(size)});\n"
    )


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("request", nargs="?", help="what to do, in plain English")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--size", type=int, default=3000, help="working long edge in px (0 = original)")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--plan", type=Path, help="re-render a saved Plan.json without the LLM")
    ap.add_argument("--only", type=int, nargs="+", help="render only these version numbers")
    a = ap.parse_args()

    src = a.image.expanduser().resolve()
    if not src.is_file():
        fail(f"image not found: {src}")
    if not a.request and not a.plan:
        fail("give a request, or --plan to re-render a saved plan")
    if not LIB.is_file():
        fail(f"missing {LIB}")
    seed = a.seed if a.seed is not None else random.randint(0, 2**31 - 1)
    settings = load_settings()

    log(f"Image: {src}")
    if a.plan:
        saved = json.loads(a.plan.expanduser().read_text())
        plan, warnings = validate(saved.get("plan", saved), len(saved.get("plan", saved)["versions"]))
        request = saved.get("request", "(from saved plan)")
        log(f"Loaded plan: {a.plan}")
    else:
        request = a.request
        log(f"Planning {a.count} versions with {settings['model']} (seed {seed})")
        t0 = time.time()
        raw = ask_llm(settings, request, a.count, seed, None)
        try:
            plan, warnings = validate(raw, a.count)
        except ValueError as e:
            fail(f"{e}. Raw plan:\n{json.dumps(raw, indent=1)[:2000]}")
        log(f"Plan ready in {time.time() - t0:.0f}s: \"{plan['title']}\", "
            f"{len(plan['versions'])} versions, subject isolation {'on' if plan['isolate_subject'] else 'off'}")
    for w in warnings:
        log(f"WARN: {w}")

    if a.dry_run:
        print(json.dumps(plan, indent=2))
        return

    now = datetime.now()
    out_dir = OUTPUT_ROOT / f"{now:%Y}" / f"{now:%m}" / f"{now:%Y-%m-%d} {plan['title']}"
    n = 2
    base = out_dir
    while out_dir.exists():
        out_dir = base.with_name(f"{base.name} ({n})")
        n += 1
    (out_dir / "scripts").mkdir(parents=True)
    logfile = out_dir / "Generation.log"
    (out_dir / "Plan.json").write_text(json.dumps({
        "request": request, "image": str(src), "model": settings["model"], "seed": seed,
        "size": a.size, "plan": plan}, indent=2))
    log(f"Output: {out_dir}", logfile)

    done = 0
    for i, v in enumerate(plan["versions"], 1):
        if a.only and i not in a.only:
            continue
        out = out_dir / f"{i:02d} {v['name']}.jpg"
        script = out_dir / "scripts" / f"version_{i:02d}.jsx"
        script.write_text(variant_script(src, out, v, plan["isolate_subject"], a.size))
        log(f"[{i}/{len(plan['versions'])}] {v['name']}: {v['idea']}", logfile)
        t0 = time.time()
        result = photoshop(f"$.evalFile(new File({json.dumps(str(script))}))")
        secs = time.time() - t0
        if result.startswith("OK") and out.is_file():
            done += 1
            extra = result[2:].lstrip(" |")
            log(f"    saved in {secs:.0f}s" + (f" (notes: {extra})" if extra else ""), logfile)
        else:
            log(f"    FAILED after {secs:.0f}s: {result}", logfile)
            if "osascript" in result and done == 0:
                fail("could not talk to Photoshop. Is it installed, and has Terminal been "
                     "allowed to control it (System Settings > Privacy & Security > Automation)?", logfile)

    log(f"Done: {done} JPEG(s) in {out_dir}", logfile)


if __name__ == "__main__":
    main()
