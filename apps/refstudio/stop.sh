#!/bin/zsh
# Stop RefStudio. (A generation in progress in ComfyUI carries on until it finishes.)
/usr/bin/pkill -f "refstudio/app.py" && echo "RefStudio stopped" || echo "RefStudio wasn't running"
