# --------------------------------------------------------------------
# cxx.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Tuesday August 29, 2023
# --------------------------------------------------------------------

from typing import Iterable, Optional

from xeno.recipes.c import compile as base_compile
from xeno.shell import select_env
from xeno.typedefs import PathSpec

# --------------------------------------------------------------------
ENV = select_env("PATH", "CXX", "CFLAGS", "LDFLAGS", CXX="clang++").append(
    CFLAGS=("-Wall", "--std=c++2a")
)


# --------------------------------------------------------------------
def compile(
    *sources: PathSpec,
    obj=False,
    headers: Iterable[PathSpec] = [],
    target: Optional[PathSpec] = None,
    env=ENV,
):
    return base_compile(
        *sources, obj=obj, headers=headers, target=target, env=env, compiler_var="CXX"
    )
