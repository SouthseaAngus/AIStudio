#!/bin/zsh
# Pick a folder of photos and build a 3D model in the background; the model opens when done.
# Safe to run from Stream Deck, Hazel or Finder: needs no terminal.
# Or pass the folder: start.sh ~/Pictures/my-object
setopt extended_glob   # for the case-insensitive photo search below
APP_DIR="${0:A:h}"
ROOT="${APP_DIR:h:h}"
LOG="$APP_DIR/photoscan.log"
DETAIL="${PHOTOSCAN_DETAIL:-medium}"

notify() {
  /usr/bin/osascript -e 'on run argv' \
    -e 'display notification (item 2 of argv) with title "Photoscan" subtitle (item 1 of argv)' \
    -e 'end run' -- "$1" "$2"
}

if [[ "$1" == "--run" ]]; then   # the background half: start.sh re-launches itself with this
  photos="$2"; name="${photos:t}"
  base="$ROOT/Output/$(date +%Y/%m)/$(date +%F) $name Scan"
  out="$base"; n=2
  while [[ -e "$out" ]]; do out="$base ($n)"; ((n++)); done
  model="$out/$name.usdz"
  cd "$ROOT" || exit 1
  echo "---- $(date '+%Y-%m-%d %H:%M:%S') $photos ($DETAIL)" >>"$LOG"
  if [[ ! -x "$APP_DIR/photoscan" ]]; then
    "$APP_DIR/build.sh" >>"$LOG" 2>&1
  fi
  if "$APP_DIR/photoscan" "$photos" "$model" --detail "$DETAIL" >>"$LOG" 2>&1; then
    echo >>"$LOG"
    notify "$name" "The 3D model is ready."
    /usr/bin/open "$model"
  else
    echo >>"$LOG"
    rmdir "$out" 2>/dev/null   # leave no empty folder behind
    notify "$name" "Couldn't finish. The log is open in Console."
    /usr/bin/open -a Console "$LOG"
  fi
  exit 0
fi

if /usr/bin/pgrep -f "^$APP_DIR/photoscan " >/dev/null; then
  notify "Still working" "Wait for the current scan to finish."
  exit 0
fi

photos="$1"
if [[ -z "$photos" ]]; then
  photos="$(/usr/bin/osascript -e 'activate' \
    -e 'POSIX path of (choose folder with prompt "Choose a folder of photos for Photoscan" default location (path to pictures folder))' 2>/dev/null)"
  [[ -z "$photos" ]] && exit 0   # cancelled
fi
photos="${photos:A}"   # tidy the path: no trailing slash, so the name is the folder's
[[ -d "$photos" ]] || { notify "Not found" "$photos"; exit 1 }

images=("$photos"/*.(#i)(jpg|jpeg|heic|png|tif|tiff)(N.))
if (( ${#images} == 0 )); then
  notify "${photos:t}" "No photos found in that folder."
  exit 1
fi

notify "${photos:t}" "Scanning ${#images} photos. The model opens when it's done."
nohup "$0" --run "$photos" >/dev/null 2>&1 &!   # &! = detach from this shell
exit 0
