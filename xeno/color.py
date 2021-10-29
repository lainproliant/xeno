# --------------------------------------------------------------------
# color.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Wednesday October 28, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------
import os
import sys
from typing import List, Optional

# --------------------------------------------------------------------
_ansi_enabled = (
    "NO_COLOR" not in os.environ and sys.stdout.isatty()
) or "FORCE_COLOR" in os.environ

# --------------------------------------------------------------------
def disable():
    global _ansi_enabled
    _ansi_enabled = False


# --------------------------------------------------------------------
def enable():
    global _ansi_enabled
    _ansi_enabled = True


# --------------------------------------------------------------------
COLORS = ("black", "red", "green", "yellow", "blue", "magenta", "cyan", "white")
RENDER_MODES = (
    "none",
    "bold",
    "dim",
    "italic",
    "underline",
    "blink",
    "blink2",
    "negative",
    "concealed",
    "crossed",
)

# --------------------------------------------------------------------
ANSI_ESC = "\033["

# --------------------------------------------------------------------
def seq(code) -> str:
    return ANSI_ESC + str(code)


# --------------------------------------------------------------------
def attr(*parts) -> str:
    return seq(";".join(str(p) for p in parts)) + "m"


# --------------------------------------------------------------------
def clreol():
    if sys.stdout.isatty():
        sys.stdout.write(seq("K"))
        sys.stdout.flush()


# --------------------------------------------------------------------
def show_cursor():
    if sys.stdout.isatty():
        sys.stdout.write(seq("?25h"))
        sys.stdout.flush()


# --------------------------------------------------------------------
def hide_cursor():
    if sys.stdout.isatty():
        sys.stdout.write(seq("?25l"))


# --------------------------------------------------------------------
RESET = attr(0)

# --------------------------------------------------------------------
def style(
    fg: Optional[str] = None, bg: Optional[str] = None, render: Optional[str] = None
):
    attr_codes: List[int] = []

    if render is not None:
        attr_codes.append(RENDER_MODES.index(render))
    if fg is not None:
        attr_codes.append(30 + COLORS.index(fg))
    if bg is not None:
        attr_codes.append(40 + COLORS.index(bg))

    return attr(*attr_codes)


# --------------------------------------------------------------------
def color(
    *content,
    fg: Optional[str] = None,
    bg: Optional[str] = None,
    render: Optional[str] = None,
    after: str = ""
) -> str:
    if _ansi_enabled:
        before = style(fg, bg, render)
        return before + "".join(str(obj) for obj in content) + RESET + after
    return "".join(str(obj) for obj in content)
