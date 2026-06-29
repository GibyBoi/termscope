"""Shared colors, fonts and spacing for a sleek, modern dark UI (Tokyo-Night-ish)."""
from __future__ import annotations

# Core palette
BG = "#16161e"          # app background (deep ink)
SURFACE = "#1a1b26"     # panels
SURFACE_2 = "#1f2335"   # cards / raised
SURFACE_3 = "#24283b"   # hover / inputs
BORDER = "#2a2e43"

TEXT = "#c0caf5"        # primary text
TEXT_MUTED = "#7982a9"  # secondary text
TEXT_FAINT = "#565f89"  # tertiary

ACCENT = "#7aa2f7"      # primary blue
ACCENT_HOVER = "#8fb0f8"
ACCENT_DIM = "#3d59a1"
GREEN = "#9ece6a"       # learned / success
GREEN_HOVER = "#aede7c"
PURPLE = "#bb9af7"
CYAN = "#7dcfff"
RED = "#f7768e"
ORANGE = "#ff9e64"
GOLD = "#e0af68"
TEAL = "#73daca"

# Category accent colors
CATEGORY_COLORS = {
    "tech": CYAN,
    "business": ORANGE,
    "companies": TEAL,
    "general": PURPLE,
}


def category_color(category: str) -> str:
    return CATEGORY_COLORS.get(category, ACCENT)


# Typography (Segoe UI is the native Windows 11 face)
FONT = "Segoe UI"
FONT_SEMIBOLD = "Segoe UI Semibold"

SIZE_TITLE = 26
SIZE_H1 = 20
SIZE_H2 = 16
SIZE_BODY = 13
SIZE_SMALL = 11
SIZE_TINY = 10

# Spacing
PAD = 16
PAD_SM = 8
RADIUS = 12
