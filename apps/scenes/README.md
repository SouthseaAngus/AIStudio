# Key Scenes

**Give it a film and it picks out the key scenes.** For each scene you get a title, the defining line of dialogue, what happens and why it matters, how long it runs, a still and a clip you can replay.

Everything runs on the Mac Studio. Nothing leaves your computer.

```zsh
cd ~/AIStudio && source .venv/bin/activate
python apps/scenes/scenes.py "/Volumes/Extended/rip/FilmDVDs/James Bond/03 Goldfinger.mp4"
```

**From Stream Deck:** press the Key Scenes button and choose a film. A notification says it has started, and Safari opens the report when it's done, a few minutes later. Only one film runs at a time; pressing the button again while it's working just says so. If a run fails, the log opens in Console.

| Stream Deck setting | Command |
|---|---|
| Run | `/Users/angus/AIStudio/apps/scenes/start.sh` |
| Status (running / stopped) | `/Users/angus/AIStudio/apps/scenes/status.sh` |
| Stop a run part-way | `/Users/angus/AIStudio/apps/scenes/stop.sh` |

The button uses gpt-oss:120b. To use another model, set `SCENES_MODEL` (e.g. `SCENES_MODEL=gemma4:26b /Users/angus/AIStudio/apps/scenes/start.sh`). Its output goes to `apps/scenes/scenes.log`.

When it finishes, open **Key Scenes.html** in the run folder:

```
~/AIStudio/Output/YYYY/MM/YYYY-MM-DD Goldfinger Key Scenes/
    Key Scenes.html     the report: click a still to play the scene
    Scenes.json         the scene list, with timings
    Still_01.jpg ...    one still per scene, taken at the defining line
    Clip_01.mp4 ...     each scene as its own clip
    Transcript.json     what the LLM read
    LLM.json            the LLM's raw answers, for checking its choices
    Film.mp4            a link to the film itself, for "Play the film from here"
    Generation.log
```

## How it works

1. **Whisper listens to the film.** `mlx-whisper` (large-v3-turbo) turns the soundtrack into a transcript, with a timestamp on every line. This takes a few minutes the first time. The transcript is cached in `Output/.scenes-cache/`, so later runs on the same film skip this step.
2. **The LLM picks the scenes from the transcript.** The model (`--model`, or the orchestrator in `config.yaml`) reads the whole timed transcript and chooses the key scenes from what is actually said, with its memory of the film only as a hint. Memory alone isn't trustworthy: asked to recall Goldfinger, gpt-oss invented a Rolls-Royce crash and a roulette game at "Casino Royale". Each scene's line is then found in the transcript and anchors the scene. If the model mistypes a time, the scene moves to where the line is said. The scene widens to the whole exchange around it.
3. **ffmpeg makes the stills and clips.** The still is taken just after the scene's defining line (e.g. *"No, Mr Bond, I expect you to die!"*). Each clip is cut with a couple of seconds' lead-in and run-out.

## Options

```
--scenes 15          how many scenes (default 10)
--title "Goldfinger" the film's name, if the filename doesn't make it clear
--model gpt-oss:120b use a different Ollama model
--no-clips           don't cut clips; the report plays the film itself from each scene's start
--aspect 16:9        force the picture shape, if stills look squashed or stretched
--dry-run            just print the scene list; make no files
```

## Things to know

- **The film needs English dialogue.** Whisper is set to English. A silent film or one with very little speech gives the LLM little to time scenes against.
- **Timings are approximate.** They come from where the dialogue starts and stops, so a scene may start a few seconds early or late. Change the times in `Scenes.json` if you need them exact.
- **The LLM can misjudge.** It works best on well-known films, where its own knowledge backs up the transcript. Scenes with a famous line are timed best. Action scenes with no dialogue are placed by guesswork and are sometimes off, or attached to the wrong scene.
- **About two minutes per film** once the transcript is cached, clips included. The model gets about 3,000 tokens of thinking, then has to answer. Without a limit, some models (gemma4) second-guess their list until the reply runs out.
- **Model:** gpt-oss:120b reads transcripts well. Thinking models take `think` as on/off, except gpt-oss, which takes a level (medium to choose, low to answer).
- **Sometimes fewer scenes than asked for.** If the model lists one scene twice under two names, the duplicate is dropped.
- **Squashed pictures are fixed automatically.** Some DVD rips are flagged 4:3 when the picture is really widescreen, so everyone looks thin (Goldfinger is one). When the file says 4:3, the picture has no black bars, and the LLM knows the film is widescreen, the stills and clips are made at 16:9. Use `--aspect` if it gets one wrong.
- **"Play the film from here"** loads the whole film into that scene's player, starting at the scene. Browsers won't play a video from a different folder than the page, so the run folder holds `Film.mp4`, a link to the film where you pointed the script at it (e.g. `/Volumes/video/...`). It only works while that drive or share is connected, and only for files the browser can play (.mp4 or .m4v, not .mkv). The clips work anywhere.
- **Lines are checked against the transcript.** A line is shown only if the transcript really has it, closely matched, and the line fixes where its scene is.

Requires: `pip install mlx-whisper` (in the AIStudio `.venv`) and ffmpeg (Homebrew).
