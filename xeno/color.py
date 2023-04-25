# --------------------------------------------------------------------
# color.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Wednesday October 28, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------
import io
import os
import sys
from functools import partial
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
def is_enabled():
    global _ansi_enabled
    return _ansi_enabled


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


# --------------------------------------------------------------------
class TextDecorator:
    def __init__(
        self,
        *,
        fg: Optional[str] = None,
        bg: Optional[str] = None,
        render: Optional[str] = None,
        outfile=sys.stdout
    ):
        self.fg = fg
        self.bg = bg
        self.render = render
        self.outfile = outfile
        self.wipe = 0

    def embrace(
        self,
        text,
        *,
        begin="[",
        end="]",
        brace_fg="white",
        brace_bg=None,
        brace_render="bold",
        **kwargs
    ):
        self._autowipe()
        brace_color = partial(color, fg=brace_fg, bg=brace_bg, render=brace_render)
        sb = io.StringIO()
        sb.write(brace_color(begin))
        sb.write(color(text, **kwargs))
        sb.write(brace_color(end))
        return self.outfile.write(sb.getvalue() + " ")

    def write(self, text, **kwargs):
        return self.outfile.write(color(text, **self._inject_kwargs(kwargs)))

    def print(self, text, **kwargs):
        self._autowipe()
        n = self.write(text, **kwargs)
        n += self.outfile.write("\n")
        self.flush()
        return n

    def flush(self):
        return self.outfile.flush()

    def wipeline(self, n: int):
        if n > 0:
            self.outfile.write("\r")
            self.outfile.write(" " * n)
            self.outfile.write("\r")
            self.flush()

    def _inject_kwargs(self, kwargs):
        return {
            **kwargs,
            "fg": self.fg or kwargs.get("fg", None),
            "bg": self.bg or kwargs.get("bg", None),
            "render": self.render or kwargs.get("render", None),
        }

    def _autowipe(self):
        self.wipeline(self.wipe)
        self.wipe = 0

    def __call__(self, text, **kwargs):
        return self.print(text, **kwargs)
