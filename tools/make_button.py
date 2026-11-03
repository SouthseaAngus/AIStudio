"""Make a Stream Deck button from a generated icon.

    python tools/make_button.py "Output/2026/11/2026-11-03 KeyScene/Image_01.png" --label KeyScenes

Writes Button_01.png beside the image: a white glyph on pure black, scaled to
nearly fill the key, with the label set in San Francisco Bold underneath. Any
text the model drew under the glyph is replaced by the label.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modules.button_icon import SIZE, make_button  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Make a Stream Deck button from a generated icon.")
    parser.add_argument("image", help="the generated icon")
    parser.add_argument("--label", default="", help="text under the glyph (default: none)")
    parser.add_argument("--out", help="where to save (default: Button_NN.png beside the image)")
    parser.add_argument("--size", type=int, default=SIZE, help=f"pixels square (default {SIZE})")
    parser.add_argument("--keep-text", action="store_true", help="keep text the model drew")
    parser.add_argument("--colour", default="white", help="glyph and label colour (default white)")
    args = parser.parse_args()

    src = Path(args.image).expanduser()
    out = Path(args.out).expanduser() if args.out else src.with_name(src.name.replace("Image_", "Button_"))
    if out == src:
        out = src.with_name(f"{src.stem} Button.png")
    print(make_button(src, out, args.label, args.size, args.keep_text, args.colour))


if __name__ == "__main__":
    main()
