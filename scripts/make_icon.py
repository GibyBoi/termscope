#!/usr/bin/env python
"""Generate the TermScope app logo/icon (redrawn from the v2 reference art).

Concept: a blue "scope" lens (ring) with a green pupil; three blue signal waves
sweeping out to the upper-right; and a green "C" arc wrapping the left side.
Evokes a scope actively listening and picking up terms. Rendered supersampled for
crisp edges on a transparent background; saved as a 1024px PNG — the single
source image for `npm run tauri icon assets/termscope.png`, which generates the
platform icon set under `src-tauri/icons/` (including the Windows .ico).
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
PNG_OUT = ROOT / "assets" / "termscope.png"

BLUE = (43, 163, 227, 255)    # azure ~ #2BA3E3 (lens + signal waves)
GREEN = (54, 169, 76, 255)    # ~ #36A94C (pupil + left arc)

# --dev palette: the SAME drawing, all red — marks the v3 development app so it
# is unmistakable next to the installed release icon.
DEV_PRIMARY = (227, 59, 59, 255)     # bright red ~ #E33B3B (lens + signal waves)
DEV_SECONDARY = (156, 28, 28, 255)   # deep red ~ #9C1C1C (pupil + left arc)


def render(size: int, primary=BLUE, secondary=GREEN) -> Image.Image:
    SS = 4  # supersample for smooth arcs
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    cx, cy = s * 0.46, s * 0.52  # lens centre (slightly left, vertically centred)

    def arc(radius, start, end, color, width):
        bb = [cx - radius, cy - radius, cx + radius, cy + radius]
        d.arc(bb, start=start, end=end, fill=color, width=int(width))

    # Three signal waves sweeping the upper-right (outer-most first looks fine).
    wave_w = s * 0.044
    for r in (0.225, 0.30, 0.375):
        arc(s * r, -110, 62, primary, wave_w)

    # "C" wrapping the left side, opening toward the lens.
    arc(s * 0.255, 118, 236, secondary, s * 0.058)

    # Lens ring + pupil.
    r = s * 0.155
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=primary, width=int(s * 0.052))
    rp = s * 0.055
    d.ellipse([cx - rp, cy - rp, cx + rp, cy + rp], fill=secondary)

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dev",
        action="store_true",
        help="render the all-red v3 development palette instead of the release colors",
    )
    args = ap.parse_args()
    colors = (
        {"primary": DEV_PRIMARY, "secondary": DEV_SECONDARY} if args.dev else {}
    )
    PNG_OUT.parent.mkdir(parents=True, exist_ok=True)
    img = render(1024, **colors)
    img.save(PNG_OUT)
    print(f"wrote {PNG_OUT}{' (dev/red palette)' if args.dev else ''}")
    # The sidebar logo is the same art; keep it in sync with the icon source.
    sidebar = ROOT / "src" / "assets" / "termscope.png"
    if sidebar.parent.is_dir():
        img.save(sidebar)
        print(f"wrote {sidebar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
