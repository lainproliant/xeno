# --------------------------------------------------------------------
# util.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday May 7, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
import inspect
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .errors import InjectionError


# --------------------------------------------------------------------
async def async_map(key, coro):
    """
    Wraps a coroutine so that when executed, the coroutine result
    and the mapped value are provided.  Useful for gathering results
    from a map of coroutines.
    """
    return key, await coro


# --------------------------------------------------------------------
async def async_wrap(f, *args, **kwargs):
    """
    Wraps a normal function in a coroutine.  If the given function
    is already a coroutine function, we simply yield from it.
    """
    if not asyncio.iscoroutinefunction(f):
        return f(*args, **kwargs)
    return await f(*args, **kwargs)


# --------------------------------------------------------------------
def bind_unbound_method(obj, method):
    return method.__get__(obj, obj.__class__)


# --------------------------------------------------------------------
def decode(b: bytes) -> str:
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("ISO-8859-1")


# --------------------------------------------------------------------
def get_params_from_signature(f):
    """
    Fetches the params tuple list from the given function's signature.
    """
    sig = inspect.signature(f)
    return list(sig.parameters.values())


# --------------------------------------------------------------------
def is_iterable(obj: Any) -> bool:
    """Determine if the given object is an iterable sequence other than a string or byte array."""
    return (
        isinstance(obj, Sequence)
        and not isinstance(obj, (str, bytes, bytearray))
        or inspect.isgenerator(obj)
    )


# --------------------------------------------------------------------
def file_age(file: Path) -> timedelta:
    return datetime.now() - datetime.fromtimestamp(file.stat().st_mtime)


# --------------------------------------------------------------------
def resolve_alias(name, aliases, visited=None):
    if visited is None:
        visited = set()

    if name in aliases:
        if name in visited:
            raise InjectionError(
                "Alias loop detected: %s -> %s" % (name, ",".join(visited))
            )
        visited.add(name)
        name = resolve_alias(aliases[name], aliases, set(visited))
    return name
