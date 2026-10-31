#!/bin/zsh
# Start RefStudio in the background (if it isn't already running) and open it.
# Safe to run from Stream Deck, Hazel or Finder: needs no terminal or venv activation.
APP_DIR="${0:A:h}"
ROOT="${APP_DIR:h}"
URL="http://127.0.0.1:8765"
LOG="$APP_DIR/refstudio.log"

if /usr/bin/curl -sf "$URL/api/status" >/dev/null 2>&1; then
  /usr/bin/open "$URL"          # already running: just bring the page up
  exit 0
fi

cd "$ROOT" || exit 1
echo "---- $(date '+%Y-%m-%d %H:%M:%S') start" >>"$LOG"
nohup "$ROOT/.venv/bin/python" "$APP_DIR/app.py" >>"$LOG" 2>&1 &!   # &! = detach from this shell

for i in {1..30}; do
  sleep 0.5
  /usr/bin/curl -sf "$URL/api/status" >/dev/null 2>&1 && exit 0   # the app opens the browser itself
done
echo "RefStudio didn't start; see $LOG" >&2
exit 1
