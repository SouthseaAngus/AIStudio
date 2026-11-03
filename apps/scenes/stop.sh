#!/bin/zsh
# Stop a Key Scenes run part-way. The transcript is kept if it was finished, so a re-run is quicker.
/usr/bin/pkill -f "scenes/scenes.py" && echo "Key Scenes stopped" || echo "Key Scenes wasn't running"
