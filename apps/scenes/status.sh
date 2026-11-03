#!/bin/zsh
# Exit 0 and print "running" while Key Scenes is working on a film, else exit 1: for Stream Deck polling.
if /usr/bin/pgrep -f "scenes/scenes.py" >/dev/null; then echo running; exit 0; fi
echo stopped; exit 1
