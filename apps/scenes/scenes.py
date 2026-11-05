#!/usr/bin/env python3
"""Key Scenes: ask the local LLM to pick out a film's key scenes.

    cd ~/AIStudio && source .venv/bin/activate
    python apps/scenes/scenes.py "/Volumes/Extended/rip/FilmDVDs/James Bond/03 Goldfinger.mp4"

Steps:
    1. Whisper (mlx-whisper, on this Mac) transcribes the soundtrack with
       timestamps. The transcript is cached, so a rerun skips this step.
    2. The orchestrator model reads the timed transcript, plus what it already
       knows about the film, and returns the key scenes as JSON: title, start,
       end, the defining line of dialogue and why the scene matters.
    3. ffmpeg grabs a still at that line and cuts a clip of each scene.

Each run is saved like any AIStudio run:

    ~/AIStudio/Output/YYYY/MM/YYYY-MM-DD <Film> Key Scenes/
        Key Scenes.html     the report: open it in a browser
        Scenes.json         the scene list, with timings
        Still_01.jpg ...    one still per scene
        Clip_01.mp4 ...     each scene, to replay
        Transcript.json     the timed transcript the LLM read
        Generation.log
"""

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from modules.config import load_config  # noqa: E402
from modules.logger import RunLogger  # noqa: E402
from modules.ollama_client import OllamaClient  # noqa: E402

import requests  # noqa: E402

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
CACHE_DIR_NAME = ".scenes-cache"
NUM_CTX = 65536             # a feature film's transcript is ~15-25k tokens
PAD_BEFORE = 2.0            # seconds of lead-in before the LLM's start
PAD_AFTER = 3.0             # and run-out after its end
THINK_BUDGET = 12000        # characters (~3k tokens) of thinking before the model must answer
MIN_SCENE = 15.0
MAX_SCENE = 6 * 60.0

SCENES_PROMPT = """You are a film editor building a "key scenes" reel.

You are given a film's title, its running time and a timed transcript of its
soundtrack: one line per stretch of speech, each starting [HH:MM:SS]. Gaps
between lines are music, action or silence.

Read the transcript and choose the {count} most important scenes: the ones that
turn the plot, hold the film's best-known lines, or are its famous set pieces.
Judge from what is actually said in the transcript. What you remember of the
film is only a hint, and may be wrong: every scene, line and timing must come
from the transcript.

Return JSON only, in this shape:
{{
  "film": "<title, with year>",
  "aspect_ratio": "<the film's original aspect ratio as released, e.g. 1.85:1, 2.39:1, 1.37:1>",
  "scenes": [
    {{
      "title": "<short scene name, as a fan would say it>",
      "start": "HH:MM:SS",
      "end": "HH:MM:SS",
      "line": "<the scene's most famous line, copied word for word from the transcript, or empty>",
      "summary": "<one or two sentences: what happens>",
      "why": "<one or two sentences: why it is a key scene>"
    }}
  ]
}}

Rules:
- Scenes in film order, each a different moment of the film.
- start is the first transcript line of the scene; end is where it cuts away.
  Most scenes run 1-4 minutes.
- No markdown, no commentary outside the JSON."""


# ---------------------------------------------------------------- helpers

def hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def parse_hms(text) -> float | None:
    if isinstance(text, (int, float)):
        return float(text)
    m = re.fullmatch(r"\s*(?:(\d+):)?(\d{1,2}):(\d{2}(?:\.\d+)?)\s*", str(text))
    if not m:
        return None
    h, mnt, sec = m.groups()
    return int(h or 0) * 3600 + int(mnt) * 60 + float(sec)


def duration_label(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def run(cmd: list, logger, what: str):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        logger.fail(f"{cmd[0]} not found; install it with: brew install ffmpeg")
    if r.returncode != 0:
        logger.fail(f"{what} failed:\n{r.stderr[-2000:]}")
    return r.stdout


def probe_duration(movie: Path, logger) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", str(movie)], logger, "ffprobe")
    return float(out.strip())


def safe_name(text: str) -> str:
    return re.sub(r"[^\w .,'()&-]+", "", text).strip() or "Film"


# ---------------------------------------------------------------- transcript

def transcribe(movie: Path, cache_dir: Path, logger) -> list:
    """Timed transcript as [{start, end, text}], cached per movie file."""
    st = movie.stat()
    # Keyed on name and size, not path, so a copy on another drive reuses it
    key = hashlib.sha1(f"{movie.name}|{st.st_size}".encode()).hexdigest()[:12]
    cache = cache_dir / f"{safe_name(movie.stem)}-{key}.json"
    if cache.is_file():
        logger.log(f"Transcript loaded from cache ({cache.name})")
        return json.loads(cache.read_text(encoding="utf-8"))

    try:
        import mlx_whisper
    except ImportError:
        logger.fail("mlx-whisper is not installed: pip install mlx-whisper")

    logger.log(f"Transcribing soundtrack with {WHISPER_MODEL.split('/')[-1]} (a few minutes)")
    result = mlx_whisper.transcribe(
        str(movie),
        path_or_hf_repo=WHISPER_MODEL,
        language="en",
        condition_on_previous_text=False,   # stops runaway repeats over music
        verbose=None,
    )
    segments = []
    for seg in result.get("segments", []):
        text = seg["text"].strip()
        # Whisper invents captions over music and silence; drop the usual ones
        if not text or re.fullmatch(r"(?i)[\W_]*(thank you\.?|you|music|\.+)[\W_]*", text):
            continue
        if segments and text == segments[-1]["text"]:
            continue
        segments.append({"start": round(seg["start"], 2), "end": round(seg["end"], 2), "text": text})

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(segments, indent=1, ensure_ascii=False), encoding="utf-8")
    logger.log(f"Transcript finished: {len(segments)} lines")
    return segments


def transcript_text(segments: list) -> str:
    return "\n".join(f"[{hms(s['start'])}] {s['text']}" for s in segments)



# ---------------------------------------------------------------- LLM

def think_mode(model: str, on: bool):
    """Ollama's think setting: gpt-oss takes a level and can't be switched off."""
    if model.startswith("gpt-oss"):
        return "medium" if on else "low"
    return on


def think_then_answer(ollama: OllamaClient, system: str, user: str, logger) -> dict:
    """Let a thinking model reason up to THINK_BUDGET, then make it answer.

    Left alone, gemma4 drafts a good scene list and then second-guesses it
    until the reply runs out. So stream its thinking, stop at the budget, and
    ask again with thinking off and its notes in hand."""
    payload = {
        "model": ollama.model, "stream": True, "think": think_mode(ollama.model, True),
        "options": {"temperature": ollama.temperature, "num_ctx": ollama.num_ctx},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    thinking, content = [], []
    try:
        with requests.post(f"{ollama.host}/api/chat", json=payload, stream=True, timeout=600) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                msg = json.loads(line).get("message", {}) if line else {}
                thinking.append(msg.get("thinking") or "")
                content.append(msg.get("content") or "")
                if sum(map(len, thinking)) > THINK_BUDGET and not "".join(content).strip():
                    break
    except requests.RequestException as e:
        logger.fail(f"Ollama request failed: {e}")

    answer = "".join(content)
    if "{" in answer and "}" in answer:
        try:
            return json.loads(answer[answer.find("{"):answer.rfind("}") + 1])
        except json.JSONDecodeError:
            pass
    notes = "".join(thinking)[-THINK_BUDGET:]
    return ollama.structured_json(
        system, f"{user}\n\nYour notes so far:\n{notes}\n\nStop deliberating. Give your answer now, as JSON.",
        timeout=900, think=think_mode(ollama.model, False))


# ---------------------------------------------------------------- scenes

def words(text: str) -> str:
    return re.sub(r"\W+", " ", text).lower().strip()


def find_quote(quote_text: str, segments: list, start: float, end: float,
               window: float = 30.0) -> tuple[float, str] | None:
    """The transcript line matching the quote, within `window` seconds of the
    scene: (time, the words as the transcript has them), or None.

    Strict on purpose: a loose match pins a famous line on the wrong scene.
    A line Whisper split in two is matched against pairs of lines too."""
    q = words(quote_text)
    if len(q) < 4:
        return None
    best, best_score = None, 0.0
    near = [seg for seg in segments if seg["end"] >= start - window and seg["start"] <= end + window]
    for i, seg in enumerate(near):
        candidates = [(seg["text"],)]
        if i + 1 < len(near):
            candidates.append((seg["text"], near[i + 1]["text"]))
        for parts in candidates:
            t = words(" ".join(parts))
            score = 1.0 if q in t else SequenceMatcher(None, q, t).ratio()
            if score > best_score:
                best, best_score = (seg["start"], " ".join(parts)), score
    return best if best_score >= 0.75 else None


def dialogue_run_start(segments: list, start: float, gap: float = 4.0, limit: float = 120.0) -> float:
    """Pull start back to the opening of the exchange it lands in: follow lines
    that end within `gap` seconds of the next, for at most `limit` seconds."""
    first = start
    for seg in reversed(segments):
        if seg["start"] >= start:
            continue
        if seg["end"] < first - gap or seg["start"] < start - limit:
            break
        first = min(first, seg["start"])
    return first


def dialogue_run_end(segments: list, end: float, gap: float = 4.0, limit: float = 120.0) -> float:
    """Push end on to the close of the exchange it lands in, so a clip doesn't
    stop mid-conversation: follow lines that start within `gap` seconds of the
    last, for at most `limit` seconds."""
    last = end
    for seg in segments:
        if seg["end"] <= end:
            continue
        if seg["start"] > last + gap or seg["end"] > end + limit:
            break
        last = max(last, seg["end"])
    return last


def clean_scenes(raw: list, segments: list, runtime: float, logger) -> list:
    found = []
    for item in raw:
        title = str(item.get("title") or "Untitled scene").strip()
        start, end = parse_hms(item.get("start")), parse_hms(item.get("end"))
        if start is not None and end is not None and end < start:
            start, end = end, start
        # The scene's line, wherever it really is in the film: it anchors the
        # scene, since the model sometimes mistypes a time (01:17 for 00:17)
        match = find_quote(str(item.get("line") or ""), segments, 0.0, runtime, window=0)
        quote_at, quote_text = match if match else (None, "")
        if quote_at is not None:
            if start is None or not (start - 30 <= quote_at <= end + 30):
                if start is not None:
                    logger.log(f"Moved {title!r} to where its line is said, {hms(quote_at)}")
                start = end = quote_at
            start, end = min(start, quote_at - 10), max(end, quote_at + 10)
        elif start is None or end is None:
            logger.log(f"Skipped scene with unreadable timings: {title!r}")
            continue
        # Widen to the whole exchange, so a clip doesn't start or stop mid-conversation
        start, end = dialogue_run_start(segments, start), dialogue_run_end(segments, end)
        start = max(0.0, start - PAD_BEFORE)
        end = min(runtime, max(end + PAD_AFTER, start + MIN_SCENE))
        end = min(end, start + MAX_SCENE)
        found.append({
            "title": title,
            "start": start,
            "end": end,
            "quote": quote_text,
            "quote_at": quote_at,
            "summary": str(item.get("summary") or "").strip(),
            "why": str(item.get("why") or "").strip(),
        })

    scenes = []
    for sc in sorted(found, key=lambda s: s["start"]):
        prev = scenes[-1] if scenes else None
        if prev and sc["start"] < prev["end"]:
            overlap = prev["end"] - sc["start"]
            if overlap > 0.5 * min(prev["end"] - prev["start"], sc["end"] - sc["start"]):
                # Two names for one stretch of film: keep the one whose famous
                # line is really there
                keep, drop = (sc, prev) if sc["quote_at"] is not None and prev["quote_at"] is None else (prev, sc)
                logger.log(f"Same stretch of film as {keep['title']!r}, dropped: {drop['title']!r}")
                scenes[-1] = keep
                continue
            # A small overlap: end the earlier scene where this one starts
            if sc["start"] - prev["start"] >= MIN_SCENE:
                prev["end"] = sc["start"]
            else:
                sc["start"] = prev["end"]
        scenes.append(sc)

    for sc in scenes:
        sc["start"], sc["end"] = round(sc["start"], 2), round(sc["end"], 2)
        sc["duration"] = round(sc["end"] - sc["start"], 2)
    return scenes


# ---------------------------------------------------------------- media

def probe_video(movie: Path, logger) -> dict:
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
               "stream=width,height,sample_aspect_ratio", "-of", "json", str(movie)], logger, "ffprobe")
    st = json.loads(out)["streams"][0]
    w, h = st["width"], st["height"]
    num, _, den = (st.get("sample_aspect_ratio") or "1:1").partition(":")
    sar = int(num) / int(den) if num.isdigit() and den.isdigit() and int(num) and int(den) else 1.0
    return {"width": w, "height": h, "aspect": w * sar / h}


def picture_height(movie: Path, runtime: float, logger) -> int:
    """Height of the picture inside any black letterbox bars, from a few samples."""
    heights = []
    for frac in (0.2, 0.4, 0.6, 0.8):
        r = subprocess.run(["ffmpeg", "-v", "info", "-ss", f"{runtime * frac:.0f}", "-i", str(movie),
                            "-t", "4", "-vf", "cropdetect=limit=24:round=2", "-an", "-f", "null", "-"],
                           capture_output=True, text=True)
        found = re.findall(r"crop=\d+:(\d+):", r.stderr)
        if found:
            heights.append(int(found[-1]))
    return max(heights) if heights else 0


def parse_aspect(text) -> float | None:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:[:/x]\s*(\d+(?:\.\d+)?))?\s*(?::1)?\s*", str(text or ""))
    if not m:
        return None
    a = float(m.group(1)) / float(m.group(2) or 1)
    return a if 1.0 < a < 3.0 else None


def display_aspect(movie: Path, runtime: float, known: float | None, override: str | None, logger) -> float:
    """The shape to show the picture at.

    DVD rips are often flagged 4:3 when the picture is really anamorphic 16:9,
    so everyone looks thin. Catch that: flagged 4:3, picture fills the frame
    (no letterbox bars), yet the film is known to be widescreen."""
    if override:
        a = parse_aspect(override)
        if a is None:
            logger.fail(f"--aspect '{override}' is not a ratio like 16:9 or 1.78")
        return a
    v = probe_video(movie, logger)
    if v["aspect"] < 1.5 and known and known >= 1.6:
        if picture_height(movie, runtime, logger) >= 0.9 * v["height"]:
            logger.log(f"Picture is flagged {v['aspect']:.2f}:1 but the film is {known:.2f}:1 "
                       f"with no letterbox: showing it as 16:9 (override with --aspect)")
            return 16 / 9
    return v["aspect"]


def frame_filter(aspect: float) -> str:
    # Deinterlace if needed, then square the pixels at the true display shape
    return (f"yadif=deint=interlaced,scale=trunc(ih*{aspect:.5f}/2)*2:ih,setsar=1,"
            f"scale='min(1280,iw)':-2")


def grab_still(movie: Path, at: float, aspect: float, out: Path, logger):
    vf = frame_filter(aspect)
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(movie),
         "-frames:v", "1", "-vf", vf, "-q:v", "3", str(out)], logger, f"still {out.name}")


def cut_clip(movie: Path, start: float, end: float, aspect: float, out: Path, logger):
    vf = frame_filter(aspect)
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(movie),
         "-t", f"{end - start:.2f}", "-vf", vf,
         "-c:v", "h264_videotoolbox", "-b:v", "4M", "-c:a", "aac", "-b:a", "160k",
         "-ac", "2", "-movflags", "+faststart", str(out)], logger, f"clip {out.name}")


# ---------------------------------------------------------------- report

def write_report(run_dir: Path, film: str, movie: Path, runtime: float, scenes: list, model: str,
                 aspect: float, clips: bool):
    # Browsers won't let a page opened from disk play a video from another
    # folder, so play the film through the link beside the report if there is one
    film_link = run_dir / f"Film{movie.suffix.lower()}"
    film_src = quote(film_link.name) if film_link.is_symlink() else movie.resolve().as_uri()
    cards = []
    for i, sc in enumerate(scenes, 1):
        n = f"{i:02d}"
        if clips:
            video = f'<video src="Clip_{n}.mp4" poster="Still_{n}.jpg" controls preload="none" playsinline></video>'
        else:
            video = (f'<video class="film" src="{html.escape(film_src)}#t={sc["start"]:.0f},{sc["end"]:.0f}" '
                     f'poster="Still_{n}.jpg" controls preload="none" playsinline></video>')
        quote_html = f'<blockquote>&ldquo;{html.escape(sc["quote"])}&rdquo;</blockquote>' if sc["quote"] else ""
        cards.append(f"""
  <article class="scene" id="scene-{n}">
    <div class="media">
      {video}
    </div>
    <div class="text">
      <div class="meta"><span class="num">{n}</span>
        <span>{hms(sc['start'])} &ndash; {hms(sc['end'])}</span>
        <span class="dur">{duration_label(sc['duration'])}</span></div>
      <h2>{html.escape(sc['title'])}</h2>
      {quote_html}
      <p>{html.escape(sc['summary'])}</p>
      <p class="why"><strong>Why it matters.</strong> {html.escape(sc['why'])}</p>
      <p class="links">{f'<a href="Clip_{n}.mp4">Play clip</a> &middot;' if clips else ''}
        <button type="button" class="open-film" data-t="{sc['start']:.0f}">Play the film from here</button></p>
      <p class="film-note" aria-live="polite"></p>
    </div>
  </article>""")

    total = sum(sc["duration"] for sc in scenes)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(film)} &ndash; Key Scenes</title>
<style>
  :root {{ --bg:#f6f4ef; --card:#fff; --ink:#1c1b19; --muted:#6b675f; --accent:#a2780c; --line:#e3ded3; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#121110; --card:#1c1a18; --ink:#ece8e0; --muted:#9c968b; --accent:#d9a930; --line:#2d2a26; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 -apple-system, "Helvetica Neue", sans-serif; }}
  header {{ max-width:1100px; margin:0 auto; padding:40px 16px 8px; }}
  h1 {{ font-size:2rem; margin:0 0 4px; }}
  header p {{ color:var(--muted); margin:0; }}
  main {{ max-width:1100px; margin:0 auto; padding:16px; display:grid; gap:20px; }}
  .scene {{ display:grid; grid-template-columns:minmax(0,1.25fr) minmax(0,1fr); gap:20px;
           background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; }}
  video {{ width:100%; border-radius:8px; background:#000; display:block; aspect-ratio:16/9; object-fit:contain; }}
  .meta {{ display:flex; gap:12px; align-items:center; color:var(--muted); font-size:.9rem; font-variant-numeric:tabular-nums; }}
  .num {{ background:var(--accent); color:#fff; border-radius:6px; padding:1px 8px; font-weight:600; }}
  .dur {{ margin-left:auto; }}
  h2 {{ margin:8px 0; font-size:1.3rem; }}
  blockquote {{ margin:0 0 10px; padding-left:12px; border-left:3px solid var(--accent); font-style:italic; }}
  p {{ margin:0 0 10px; }}
  .why {{ color:var(--muted); }}
  .links a, .open-film {{ color:var(--accent); }}
  .film-note {{ color:var(--muted); font-size:.9rem; }}
  .open-film {{ font:inherit; background:none; border:0; padding:0; text-decoration:underline; cursor:pointer; }}
  /* The film itself may be mis-flagged (e.g. 4:3 for 16:9): stretch it to its true shape */
  video.film {{ aspect-ratio:{aspect:.5f}; object-fit:fill; }}
  footer {{ max-width:1100px; margin:0 auto; padding:8px 16px 40px; color:var(--muted); font-size:.85rem; }}
  @media (max-width:760px) {{ .scene {{ grid-template-columns:1fr; }} }}
</style></head>
<body>
<header>
  <h1>{html.escape(film)}</h1>
  <p>{len(scenes)} key scenes &middot; {duration_label(total)} of a {duration_label(runtime)} film</p>
</header>
<main>{''.join(cards)}
</main>
<footer>Chosen by {html.escape(model)} from a Whisper transcript of {html.escape(movie.name)},
  {datetime.now().strftime('%-d %B %Y')}. Click a still to play its scene. &ldquo;Play the film
  from here&rdquo; needs the drive holding the film connected.</footer>
<script>
  // Swap the card's player over to the whole film, starting at the scene
  const FILM = {json.dumps(film_src)};
  const WHERE = {json.dumps(str(movie))};
  document.querySelectorAll(".open-film").forEach(btn => btn.addEventListener("click", () => {{
    const card = btn.closest(".scene");
    const video = card.querySelector("video"), note = card.querySelector(".film-note");
    const t = Number(btn.dataset.t);
    if (video.dataset.film) {{ video.currentTime = t; video.play(); return; }}
    video.dataset.film = "1";
    video.classList.add("film");
    note.textContent = "Loading the film\u2026 (from a network drive this can take a few seconds)";
    // #t= starts it at the scene. play() must be called here, inside the
    // click: Safari blocks a play() that waits for the film to load first
    video.src = FILM + "#t=" + t;
    video.addEventListener("loadedmetadata", () => {{ if (video.currentTime < t - 2) video.currentTime = t; }}, {{ once: true }});
    video.addEventListener("playing", () => {{ note.textContent = ""; }}, {{ once: true }});
    video.addEventListener("error", () => {{
      delete video.dataset.film;
      note.textContent = "Couldn't play the film. Is this drive connected? " + WHERE;
    }}, {{ once: true }});
    video.play().catch(err => {{
      if (err.name === "NotAllowedError") note.textContent = "Press play to start the film.";
    }});
  }}));
</script>
</body></html>
"""
    (run_dir / "Key Scenes.html").write_text(page, encoding="utf-8")


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="Find a film's key scenes with the local LLM.")
    parser.add_argument("movie", help="path to the film (.mp4, .mkv, .m4v ...)")
    parser.add_argument("--title", help="the film's name, if the filename doesn't say it")
    parser.add_argument("--scenes", type=int, default=10, help="how many scenes (default 10)")
    parser.add_argument("--model", help="Ollama model (default: the orchestrator in config.yaml)")
    parser.add_argument("--no-clips", action="store_true", help="skip cutting clips; link into the film instead")
    parser.add_argument("--aspect", help="force the picture shape, e.g. 16:9, if stills look squashed or stretched")
    parser.add_argument("--dry-run", action="store_true", help="print the scene list; make no files")
    args = parser.parse_args()

    logger = RunLogger()
    movie = Path(args.movie).expanduser()
    if not movie.is_file():
        logger.fail(f"movie not found: {movie}")
    title = args.title or re.sub(r"^\d+\s*[-.]?\s*", "", movie.stem).strip()
    logger.log(f"Film received: {title}")

    cfg = load_config(BASE_DIR / "config.yaml", logger)
    cfg["ollama"]["num_ctx"] = max(cfg["ollama"]["num_ctx"], NUM_CTX)
    if args.model:
        cfg["ollama"]["orchestrator_model"] = args.model
    ollama = OllamaClient(cfg, logger)
    ollama.check_available()

    runtime = probe_duration(movie, logger)
    output_root = Path(cfg["output"]["root"])
    segments = transcribe(movie, output_root / CACHE_DIR_NAME, logger)
    if len(segments) < 20:
        logger.fail(f"only {len(segments)} lines of dialogue found; is there a soundtrack?")

    # The model chooses from the transcript: what's actually said. Its memory
    # of a film is too unreliable to choose from (it invents scenes).
    logger.log(f"Asking {ollama.model} for {args.scenes} key scenes")
    user = (f"Film: {title}\nRunning time: {hms(runtime)}\n\n"
            f"Transcript:\n{transcript_text(segments)}")
    reply = think_then_answer(ollama, SCENES_PROMPT.format(count=args.scenes), user, logger)
    aspect = display_aspect(movie, runtime, parse_aspect(reply.get("aspect_ratio")), args.aspect, logger)
    film = str(reply.get("film") or title).strip()
    raw = [sc for sc in reply.get("scenes") or [] if isinstance(sc, dict)]
    scenes = clean_scenes(raw, segments, runtime, logger)
    if not scenes:
        logger.fail(f"the model returned no usable scenes. Raw reply:\n{json.dumps(reply, indent=2)}")
    logger.log(f"Scenes chosen: {len(scenes)}")

    if args.dry_run:
        for i, sc in enumerate(scenes, 1):
            print(f"\n{i:02d}  {hms(sc['start'])}-{hms(sc['end'])}  ({duration_label(sc['duration'])})  {sc['title']}")
            if sc["quote"]:
                print(f'    "{sc["quote"]}"')
            print(f"    {sc['why']}")
        return

    now = datetime.now()
    run_dir = output_root / now.strftime("%Y") / now.strftime("%m") / \
        f"{now.strftime('%Y-%m-%d')} {safe_name(title)} Key Scenes"
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.attach_file(run_dir)

    for i, sc in enumerate(scenes, 1):
        n = f"{i:02d}"
        # The still is the moment of the defining line, else a third of the way in
        at = (sc["quote_at"] + 1.0) if sc["quote_at"] is not None else sc["start"] + sc["duration"] / 3
        grab_still(movie, at, aspect, run_dir / f"Still_{n}.jpg", logger)
        if not args.no_clips:
            cut_clip(movie, sc["start"], sc["end"], aspect, run_dir / f"Clip_{n}.mp4", logger)
        logger.log(f"Scene {n} saved: {sc['title']}")

    (run_dir / "LLM.json").write_text(json.dumps(reply, indent=2,
                                                  ensure_ascii=False), encoding="utf-8")
    (run_dir / "Transcript.json").write_text(json.dumps(segments, indent=1, ensure_ascii=False), encoding="utf-8")
    (run_dir / "Scenes.json").write_text(json.dumps({
        "film": film, "movie": str(movie.resolve()), "runtime": round(runtime, 2), "aspect": round(aspect, 4),
        "model": ollama.model, "whisper": WHISPER_MODEL, "created": now.isoformat(timespec="seconds"),
        "scenes": scenes,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    film_link = run_dir / f"Film{movie.suffix.lower()}"
    if film_link.is_symlink() or film_link.exists():
        film_link.unlink()
    try:
        film_link.symlink_to(movie.resolve())
    except OSError as e:
        logger.log(f"Couldn't link the film beside the report ({e}); the page will use its full path")
    write_report(run_dir, film, movie, runtime, scenes, ollama.model, aspect, clips=not args.no_clips)
    logger.log(f"Report saved: {run_dir / 'Key Scenes.html'}")


if __name__ == "__main__":
    main()
