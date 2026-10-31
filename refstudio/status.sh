#!/bin/zsh
# Exit 0 and print "running" if RefStudio is up, else exit 1: for Stream Deck polling.
if /usr/bin/curl -sf http://127.0.0.1:8765/api/status >/dev/null 2>&1; then echo running; exit 0; fi
echo stopped; exit 1
