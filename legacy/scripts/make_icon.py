#!/usr/bin/env python
"""Generate the TermScope app icon (assets/termscope.ico) — a blue diamond glyph
with a green 'listening' dot on a rounded dark tile."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "assets" / "termscope.ico"


def render(size: int = 256) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(s * 0.03)
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=int(s * 0.21),
                        fill=(26, 27, 38, 255))
    cx, cy = s // 2, int(s * 0.47)
    r = int(s * 0.23)
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)],
              fill=(122, 162, 247, 255))
    r2 = int(s * 0.11)
    d.polygon([(cx, cy - r2), (cx + r2, cy), (cx, cy + r2), (cx - r2, cy)],
              fill=(26, 27, 38, 255))
    dot = int(s * 0.075)
    dx, dy = int(s * 0.66), int(s * 0.66)
    d.ellipse([dx - dot, dy - dot, dx + dot, dy + dot], fill=(158, 206, 106, 255))
    return img


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    base = render(256)
    base.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                          (128, 128), (256, 256)])
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
