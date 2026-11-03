"""Turn a generated icon into a Stream Deck button: a white glyph on pure black,
scaled to nearly fill the key, with the label set in a real font.

FLUX can't be trusted with layout: the background comes out white or black, the
glyph sits small in the middle and any text is tiny or misspelt. So the glyph is
lifted out of whatever was generated and laid out again here, the same way every
time.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SIZE = 288          # Stream Deck keys are 72-144 px; it scales this down cleanly
MARGIN = 0.04       # of the key, on every side
LABEL_HEIGHT = 0.22 # the label's cap-to-descender height, at most, of the key
GAP = 0.03          # between glyph and label
FONTS = [("/System/Library/Fonts/SFNS.ttf", None),          # San Francisco, set to Bold below
         ("/System/Library/Fonts/HelveticaNeue.ttc", 1),    # Helvetica Neue Bold
         ("/System/Library/Fonts/Helvetica.ttc", 1)]


def ink_mask(img: Image.Image) -> np.ndarray:
    """0..1 coverage of the glyph, whichever way round the image was drawn."""
    g = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
    h, w = g.shape
    b = max(2, int(min(h, w) * 0.03))
    border = np.concatenate([g[:b].ravel(), g[-b:].ravel(), g[:, :b].ravel(), g[:, -b:].ravel()])
    if np.median(border) > 0.5:       # dark glyph on a light background
        g = 1.0 - g
    bg = float(np.median(np.concatenate([g[:b].ravel(), g[-b:].ravel(), g[:, :b].ravel(), g[:, -b:].ravel()])))
    strong = g[g > max(bg + 0.3, 0.5)]
    fg = float(np.percentile(strong, 95)) if strong.size else 1.0
    ink = np.clip((g - bg) / max(fg - bg, 1e-3), 0.0, 1.0)
    ink[ink < 0.25] = 0.0             # vignettes and paper texture
    return ink


def bands(ink: np.ndarray, min_gap: float = 0.02) -> list:
    """Horizontal runs of rows that hold ink, as (top, bottom) pairs."""
    rows = (ink > 0.5).sum(axis=1) > max(2, ink.shape[1] * 0.003)
    gap = max(2, int(ink.shape[0] * min_gap))
    out, start, last = [], None, None
    for y, on in enumerate(rows):
        if on:
            if start is None:
                start = y
            elif y - last > gap:
                out.append((start, last))
                start = y
            last = y
    if start is not None:
        out.append((start, last))
    return out


def drop_caption(ink: np.ndarray) -> np.ndarray:
    """Remove text the model put under the glyph: a short band below a gap."""
    found = bands(ink)
    if len(found) < 2:
        return ink
    top, bottom = found[-1]
    glyph_top = found[0][0]
    if bottom - top < 0.15 * ink.shape[0] and (top - glyph_top) > 0.3 * ink.shape[0]:
        ink = ink.copy()
        ink[top:bottom + 1] = 0.0
    return ink


def label_font(px: int) -> ImageFont.FreeTypeFont:
    for path, index in FONTS:
        if not Path(path).exists():
            continue
        if index is None:
            font = ImageFont.truetype(path, px)
            try:
                font.set_variation_by_name("Bold")
            except (OSError, ValueError):
                pass
            return font
        return ImageFont.truetype(path, px, index=index)
    return ImageFont.load_default(px)


def fit_label(text: str, width: int, height: int) -> ImageFont.FreeTypeFont:
    """The largest font size at which the label fits the given box."""
    lo, hi = 6, height * 2
    while lo < hi:
        mid = (lo + hi + 1) // 2
        l, t, r, b = label_font(mid).getbbox(text)
        if r - l <= width and b - t <= height:
            lo = mid
        else:
            hi = mid - 1
    return label_font(lo)


def make_button(src: Path, out: Path, label: str = "", size: int = SIZE,
                keep_text: bool = False, colour: str = "white") -> Path:
    ink = ink_mask(Image.open(src))
    if label and not keep_text:
        ink = drop_caption(ink)
    ys, xs = np.nonzero(ink > 0.1)
    if not len(xs):
        raise ValueError(f"no icon found in {src}")
    glyph = Image.fromarray((ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1] * 255).astype(np.uint8))

    m = round(size * MARGIN)
    box_w, box_h = size - 2 * m, size - 2 * m
    canvas = Image.new("RGB", (size, size), "black")
    draw = ImageDraw.Draw(canvas)
    if label:
        font = fit_label(label, box_w, round(size * LABEL_HEIGHT))
        l, t, r, b = font.getbbox(label)
        draw.text(((size - (r - l)) / 2 - l, size - m - b), label, font=font, fill=colour)
        box_h -= (b - t) + round(size * GAP)

    scale = min(box_w / glyph.width, box_h / glyph.height)
    glyph = glyph.resize((max(1, round(glyph.width * scale)), max(1, round(glyph.height * scale))),
                         Image.LANCZOS)
    canvas.paste(Image.new("RGB", glyph.size, colour),
                 ((size - glyph.width) // 2, m + (box_h - glyph.height) // 2), glyph)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return out
