#!/bin/zsh
# Stop a scan part-way. Nothing is kept, so a re-run starts from the beginning.
/usr/bin/pkill -f "^${0:A:h}/photoscan " && echo "Photoscan stopped" || echo "Photoscan wasn't running"
