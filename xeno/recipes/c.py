# --------------------------------------------------------------------
# c.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Monday August 28, 2023
# --------------------------------------------------------------------

"""
Batteries-included tools and opinionated defaults for building C programs.
"""

from pathlib import Path
from typing import Iterable, Optional

from xeno.recipe import expand, recipe
from xeno.recipes.shell import sh
from xeno.shell import select_env
from xeno.typedefs import PathSpec

# --------------------------------------------------------------------
ENV = select_env("PATH", "CC", "CFLAGS", "LDFLAGS", CC="clang").append(
    CFLAGS=("-Wall", "--std=c17")
)


# -------------------------------------------------------------------
@recipe(factory=True, sigil=lambda r: f"{r.name}:{r.target.name}")
def compile(
    *sources,
    obj=False,
    headers: Iterable[PathSpec] = [],
    target: Optional[PathSpec] = None,
    env=ENV,
):
    src, *srcs = expand(*sources)

    if obj:
        cmd = "{CC} {CFLAGS} -c {src} {srcs} {LDFLAGS} -o {target}"
        suffix = ".o"
    else:
        cmd = "{CC} {CFLAGS} {src} {srcs} {LDFLAGS} -o {target}"
        suffix = ""

    if target is None:
        target = src

    return sh(cmd, env=env, src=src, srcs=srcs, target=Path(target).with_suffix(suffix))
