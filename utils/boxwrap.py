"""One scan of a whole DVD cover (back | spine | front, as it lies flat in the case's sleeve) cut into its three
faces for the 3D box.

A keep-case sleeve is two 129-135 mm panels and a 14 mm spine, about 1.48 : 1. The spine is found by its edges:
the two strongest straight vertical lines, a spine's width apart, near the middle. When the scan has no clear
lines there, the standard proportions are used.
"""
from PIL import Image, ImageOps

SPINE_PER_HEIGHT = 14 / 190          # spine width as a share of the cover's height


def is_wrap(img: Image.Image) -> bool:
    """Wide enough to be a whole sleeve, not just a front."""
    return img.width / img.height >= 1.25


def _column_edges(img: Image.Image) -> list[float]:
    """How strongly each column boundary is a straight vertical line running the full height (0..1)."""
    g = ImageOps.grayscale(img)
    w, h = g.size
    px = g.load()
    rows = range(int(h * 0.04), int(h * 0.96), max(1, h // 160))          # sampled rows, skipping trim bleed
    out = []
    for x in range(w - 1):
        diffs = [abs(px[x + 1, y] - px[x, y]) for y in rows]
        hits = sum(1 for d in diffs if d > 18)                          # rows where this column changes colour
        out.append((sum(diffs) / (255 * len(diffs))) * 0.5 + (hits / len(diffs)) * 0.5)
    return out


def find_spine(img: Image.Image) -> tuple[int, int]:
    """(left, right) pixel columns of the spine."""
    w, h = img.size
    small = img if w <= 900 else img.resize((900, round(h * 900 / w)), Image.Resampling.BILINEAR)
    sw, sh = small.size
    edges = _column_edges(small)
    want = SPINE_PER_HEIGHT * sh
    best, best_score = None, 0.0
    lo, hi = int(sw * 0.38), int(sw * 0.56)
    for left in range(lo, hi):
        for width in range(max(3, int(want * 0.65)), int(want * 1.45) + 1):
            right = left + width
            if right >= len(edges):
                break
            score = edges[left] + edges[right] - 0.15 * abs(width - want) / want
            if score > best_score:
                best, best_score = (left + 1, right + 1), score
    if best is None or best_score < 0.55:                               # no clear lines: standard proportions
        mid, half = sw / 2, want / 2
        best = (round(mid - half), round(mid + half))
    k = w / sw
    return round(best[0] * k), round(best[1] * k)


def split(img: Image.Image) -> dict:
    """{"back", "spine", "front"} images from one whole-sleeve scan."""
    img = ImageOps.exif_transpose(img).convert("RGB")
    left, right = find_spine(img)
    w, h = img.size
    return {"back": img.crop((0, 0, left, h)), "spine": img.crop((left, 0, right, h)), "front": img.crop((right, 0, w, h))}
