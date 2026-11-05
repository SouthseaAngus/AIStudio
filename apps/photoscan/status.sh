#!/bin/zsh
# Exit 0 and print "running" while a scan is working, else exit 1: for Stream Deck polling.
if /usr/bin/pgrep -f "^${0:A:h}/photoscan " >/dev/null; then echo running; exit 0; fi
echo stopped; exit 1
