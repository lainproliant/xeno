# --------------------------------------------------------------------
# c.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Monday August 28, 2023
# --------------------------------------------------------------------

"""
Batteries-included tools and opinionated defaults for building C programs.
"""

from typing import Iterable

from xeno.recipe import recipe
from xeno.recipes.shell import sh
from xeno.shell import select_env
from xeno.typedefs import PathSpec


# --------------------------------------------------------------------
ENV = select_env(append="CFLAGS", CC="clang", CFLAGS=("-Wall", "--std=c17"))


# -------------------------------------------------------------------
@recipe(factory=True, sigil=lambda r: f"{r.name}:{r.target.name}")
def compile(
    *sources: PathSpec,
    obj=False,
    headers: Iterable[PathSpec] = [],
    env=ENV,
):
    src, *srcs = sources

    if obj:
        cmd = "{CC} {CFLAGS} {src} {srcs} {LDFLAGS} -o {target}"
        return sh(cmd, env=env, src=src, srcs=srcs, target=src.with_suffix(""))
    else:
        cmd = "{CC} {CFLAGS} -c {src} {srcs} {LDFLAGS} -o {target}"
        return sh(cmd, env=env, src=src, srcs=srcs, target=src.with_suffix(".o"))
