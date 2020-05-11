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
    "NOTHING"
]

from .attributes import (ClassAttributes, MethodAttributes,
                         get_injection_params, get_injection_points,
                         get_providers, scan_methods, NOTHING)
from .decorators import (alias, const, inject, named, namespace, provide,
                         singleton, using)
from .errors import (CircularDependencyError, ClassInjectionError,
                     InjectionError, InvalidResourceError,
                     MethodInjectionError, MissingDependencyError,
                     MissingResourceError, UndefinedNameError,
                     UnknownNamespaceError)
from .namespaces import Namespace
from .utils import async_map, async_wrap
from .async_injector import AsyncInjector
from .sync_injector import SyncInjector

# For backwards compatibility with older versions of Xeno.
Injector = AsyncInjector
