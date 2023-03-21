# -------------------------------------------------------------------
# Xeno: The Python dependency injector from outer space.
#
# Author: Lain Musgrove (lainproliant)
# Date: Sunday, August 28th 2016
#
# Released under a 3-clause BSD license, see LICENSE for more info.
# -------------------------------------------------------------------

__all__ = [
    "InjectionError",
    "MissingResourceError",
    "MissingDependencyError",
    "MethodInjectionError",
    "ClassInjectionError",
    "CircularDependencyError",
    "UndefinedNameError",
    "UnknownNamespaceError",
    "InvalidResourceError",
    "ClassAttributes",
    "MethodAttributes",
    "Namespace",
    "Tags",
    "async_map",
    "async_wrap",
    "singleton",
    "provide",
    "inject",
    "named",
    "alias",
    "namespace",
    "const",
    "using",
    "scan_methods",
    "get_injection_points",
    "get_providers",
    "get_injection_params",
    "Injector",
    "AsyncInjector",
    "SyncInjector",
    "NOTHING",
]

from .async_injector import AsyncInjector
from .attributes import (
    NOTHING,
    ClassAttributes,
    MethodAttributes,
    get_injection_params,
    get_injection_points,
    get_providers,
    scan_methods,
)
from .decorators import (
    Tags,
    alias,
    const,
    inject,
    named,
    namespace,
    provide,
    singleton,
    using,
)
from .errors import (
    CircularDependencyError,
    ClassInjectionError,
    InjectionError,
    InvalidResourceError,
    MethodInjectionError,
    MissingDependencyError,
    MissingResourceError,
    UndefinedNameError,
    UnknownNamespaceError,
)
from .namespaces import Namespace
from .sync_injector import SyncInjector
from .utils import async_map, async_wrap

# For backwards compatibility with older versions of Xeno.
Injector = AsyncInjector
