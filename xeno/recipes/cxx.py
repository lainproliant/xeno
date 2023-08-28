# --------------------------------------------------------------------
# cxx.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Tuesday August 29, 2023
# --------------------------------------------------------------------

from typing import Iterable

from xeno.recipes.c import compile as base_compile
from xeno.shell import select_env
from xeno.typedefs import PathSpec

# --------------------------------------------------------------------
ENV = select_env(
    "LDFLAGS", append="CFLAGS", CC="clang++", CFLAGS=("-Wall", "--std=c++2a")
)


# --------------------------------------------------------------------
def compile(
    *sources: PathSpec,
    obj=False,
    headers: Iterable[PathSpec] = [],
    env=ENV,
):
    return base_compile(*sources, obj=obj, headers=headers, env=env)
