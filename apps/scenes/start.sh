#!/bin/zsh
# Pick a film and find its key scenes in the background; the report opens in Safari when done.
# Safe to run from Stream Deck, Hazel or Finder: needs no terminal or venv activation.
# Or pass the film: start.sh "/Volumes/video/FilmDVDs/James Bond/03 Goldfinger.mp4"
APP_DIR="${0:A:h}"
ROOT="${APP_DIR:h:h}"
LOG="$APP_DIR/scenes.log"
MODEL="${SCENES_MODEL:-gpt-oss:120b}"
FILMS="/Volumes/video/FilmDVDs"

film_name() { echo "${1:t:r}" | sed -E 's/^[0-9]+[ .-]*//' }
notify() { /usr/bin/osascript -e "display notification \"$2\" with title \"Key Scenes\" subtitle \"$1\"" }

if [[ "$1" == "--run" ]]; then   # the background half: start.sh re-launches itself with this
  film="$2"; name="$(film_name "$film")"
  cd "$ROOT" || exit 1
  echo "---- $(date '+%Y-%m-%d %H:%M:%S') $film" >>"$LOG"
  if "$ROOT/.venv/bin/python" "$APP_DIR/scenes.py" "$film" --model "$MODEL" >>"$LOG" 2>&1; then
    report="$(grep -a 'Report saved: ' "$LOG" | tail -1 | sed 's/.*Report saved: //')"
    notify "$name" "The key scenes are ready."
    [[ -f "$report" ]] && /usr/bin/open -a Safari "$report"
  else
    notify "$name" "Couldn't finish. The log is open in Console."
    /usr/bin/open -a Console "$LOG"
  fi
  exit 0
fi

if /usr/bin/pgrep -f "scenes/scenes.py" >/dev/null; then
  notify "Still working" "Wait for the current film to finish."
  exit 0
fi

film="$1"
if [[ -z "$film" ]]; then
  where=""; [[ -d "$FILMS" ]] && where=" default location (POSIX file \"$FILMS\")"
  film="$(/usr/bin/osascript -e 'activate' \
    -e "POSIX path of (choose file with prompt \"Choose a film for Key Scenes\" of type {\"public.movie\"}$where)" 2>/dev/null)"
  [[ -z "$film" ]] && exit 0   # cancelled
fi
[[ -f "$film" ]] || { notify "Not found" "$film"; exit 1 }

notify "$(film_name "$film")" "Finding the key scenes. This takes a few minutes; Safari opens the report when it's done."
nohup "$0" --run "$film" >/dev/null 2>&1 &!   # &! = detach from this shell
exit 0
