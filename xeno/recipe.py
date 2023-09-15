# --------------------------------------------------------------------
# recipe.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday March 9, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import os
import asyncio
import inspect
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generator, Iterable, Optional, cast, no_type_check

from xeno.attributes import MethodAttributes
from xeno.events import Event, EventBus
from xeno.shell import PathSpec, remove_paths
from xeno.utils import async_map, async_vwrap, async_wrap, is_iterable, list_or_delim

# --------------------------------------------------------------------
UNICODE_SUPPORT = sys.stdout.encoding.lower().startswith("utf")


# --------------------------------------------------------------------
class Events:
    CLEAN = "clean"
    DEBUG = "debug"
    ERROR = "error"
    FAIL = "fail"
    INFO = "info"
    START = "start"
    SUCCESS = "success"
    WARNING = "warning"
    END = "end"


# --------------------------------------------------------------------
class BuildError(Exception):
    def __init__(self, recipe: "Recipe", msg=""):
        super().__init__(f"[{recipe.sigil()}] {msg}")
        self.recipe = recipe


# --------------------------------------------------------------------
class CompositeError(Exception):
    def __init__(
        self, exceptions: Iterable[Exception], msg: str = "Multiple errors occurred."
    ):
        self.msg = msg
        self.exceptions = list(exceptions)
        super().__init__(self._compose_message())

    def _indent_line(self, line: str, indent: int):
        return ("    " * indent) + line

    def _compose_message(self, indent=0):
        sb = []

        sb.append(self.msg)
        for exc in self.exceptions:
            header = f"{exc.__class__.__qualname__}: "
            lines = str(exc).split("\n")
            lines[0] = header + lines[0]

            for line in lines:
                sb.append("    " + line)

        return "\n".join(sb)


# --------------------------------------------------------------------
ListedComponents = list["Recipe"]
ComponentIterable = Iterable["Recipe"]
MappedComponents = dict[str, "Recipe" | Iterable["Recipe"]]
FormatF = Callable[["Recipe"], str]


# --------------------------------------------------------------------
class Recipe:
    DEFAULT_TARGET_PARAM = "target"
    SIGIL_DELIMITER = ":"

    active: set["Recipe"] = set()

    class Format:
        @dataclass
        class Symbols:
            target: str
            start: str
            ok: str
            fail: str
            warning: str

        def __init__(self, unicode_symbols=True):
            if UNICODE_SUPPORT and unicode_symbols:
                self.symbols = self.Symbols(
                    target="->", start="⚙", ok="✓", fail="✗", warning="⚠"
                )
            else:
                self.symbols = self.Symbols(
                    target="->", start="(*)", ok=":)", fail=":(", warning="/!\\"
                )

        def clean(self, recipe: "Recipe") -> str:
            sb: list[str | Path] = []
            sb.append("cleaned")
            if recipe.has_target():
                sb.append(recipe.target)
            return " ".join([str(s) for s in sb])

        def fail(self, recipe: "Recipe") -> str:
            return f"{self.symbols.fail} fail"

        def ok(self, recipe: "Recipe") -> str:
            return f"{self.symbols.ok} ok"

        def sigil(self, recipe: "Recipe") -> str:
            if recipe.has_target():
                return f"{recipe.name}{Recipe.SIGIL_DELIMITER}{recipe.rel_target()}"
            return recipe.name

        def start(self, recipe: "Recipe") -> str:
            return f"{self.symbols.start} start"

    class FormatOverride(Format):
        def __init__(self, fmt: "Recipe.Format", **overrides):
            self.fmt = fmt
            for key in overrides.keys():
                if not hasattr(fmt, key):
                    raise ValueError(key)
            self.overrides = overrides

        def add_override(self, key: str, value: Any):
            self.overrides[key] = value

        def __getattribute__(self, name):
            if name in ("overrides", "fmt", "add_override"):
                return super().__getattribute__(name)
            if name in self.overrides:
                return self.overrides[name]
            else:
                return self.fmt.__getattribute__(name)

    class PassMode(Enum):
        NORMAL = 0
        RESULTS = 1
        TARGETS = 2

    class ParamType(Enum):
        NORMAL = 0
        RECIPE = 1
        PATH = 2

    class Scanner:
        def __init__(self):
            self._args: list[Any] = []
            self._kwargs: dict[str, Any] = {}
            self._arg_offsets: list[int] = []
            self._kwarg_keys: list[str] = []
            self._paths: list[Path] = []

        def clear(self):
            self._args.clear()
            self._kwargs.clear()
            self._arg_offsets.clear()
            self._kwarg_keys.clear()
            self._paths.clear()

        def _scan_one(self, arg) -> tuple[Any, "Recipe.ParamType"]:
            if isinstance(arg, Recipe):
                return arg, Recipe.ParamType.RECIPE

            if is_iterable(arg):
                arg = [*arg]
                if arg and all(isinstance(x, Recipe) for x in arg):
                    return arg, Recipe.ParamType.RECIPE
                if arg and all(isinstance(x, Path) for x in arg):
                    return arg, Recipe.ParamType.PATH

            if isinstance(arg, Path):
                return arg, Recipe.ParamType.PATH

            return arg, Recipe.ParamType.NORMAL

        def has_recipes(self):
            return self._arg_offsets or self._kwarg_keys

        def num_recipes(self):
            return len(self._arg_offsets) + len(self._kwarg_keys)

        async def gather_args(self):
            """
            Await resolution of recipes in args and update args with their results.
            """
            results = await asyncio.gather(
                *[v() if isinstance(v, Recipe) else async_vwrap(v) for v in self._args]
            )
            self.scan_params(*results)

        def bind(self, f: Callable, mode: "Recipe.PassMode"):
            """
            Bind args and kwargs to the given callable.
            """
            return inspect.signature(f).bind(*self.args(mode), **self.kwargs(mode))

        async def gather_kwargs(self):
            """
            Await resolution of recipes in kwargs and update with their results.
            """
            result_tuples = asyncio.gather(
                *[
                    async_map(k, v() if isinstance(v, Recipe) else async_vwrap(v))
                    for k, v in self._kwargs.items()
                ]
            )
            results = {k: v for k, v in result_tuples}
            self.scan_params(**results)

        def gather_all(self):
            """
            Await resolution of recipes in args and kwargs and update both with
            their results.
            """

            return asyncio.gather(self.gather_args(), self.gather_kwargs())

        def scan_params(self, *args, **kwargs):
            self.clear()

            for i, arg in enumerate(args):
                self.scan(arg, offset=i)

            for k, arg in kwargs.items():
                self.scan(arg, key=k)

        def scan(
            self, arg, offset: Optional[int] = None, key: Optional[str] = None
        ) -> "Recipe.ParamType":
            arg, param_type = self._scan_one(arg)

            if param_type == Recipe.ParamType.PATH:
                if is_iterable(arg):
                    self._paths.extend(arg)
                else:
                    self._paths.append(arg)

            if offset is not None:
                self._args.append(arg)
                if param_type == Recipe.ParamType.RECIPE:
                    self._arg_offsets.append(offset)

            elif key is not None:
                self._kwargs[key] = arg
                if param_type == Recipe.ParamType.RECIPE:
                    self._kwarg_keys.append(key)

            return param_type

        def args(self, pass_mode: "Recipe.PassMode") -> list[Any]:
            match pass_mode:
                case Recipe.PassMode.NORMAL:
                    return self._args
                case Recipe.PassMode.RESULTS:
                    results = [*self._args]
                    for offset in self._arg_offsets:
                        value = results[offset]
                        if is_iterable(value):
                            results[offset] = [r.result() for r in value]
                        else:
                            results[offset] = value.result()
                    return results
                case Recipe.PassMode.TARGETS:
                    results = [*self._args]
                    for offset in self._arg_offsets:
                        value = results[offset]
                        if is_iterable(value):
                            results[offset] = [r.target_or(r) for r in value]
                        else:
                            results[offset] = value.target_or(value)
                    return results

        def kwargs(self, pass_mode: "Recipe.PassMode") -> dict[str, Any]:
            match pass_mode:
                case Recipe.PassMode.NORMAL:
                    return self._kwargs
                case Recipe.PassMode.RESULTS:
                    results = {**self._kwargs}
                    for key in self._kwarg_keys:
                        value = results[key]
                        if is_iterable(value):
                            results[key] = [r.result() for r in value]
                        else:
                            results[key] = value.result()
                    return results
                case Recipe.PassMode.TARGETS:
                    results = {**self._kwargs}
                    for key in self._kwarg_keys:
                        value = results[key]
                        if is_iterable(value):
                            results[key] = [r.target_or(r) for r in value]
                        else:
                            results[key] = value.target_or(value)
                    return results

        def paths(self):
            return self._paths

        def component_list(self) -> ListedComponents:
            return [self._args[x] for x in self._arg_offsets]

        def component_map(self) -> MappedComponents:
            return {k: self._kwargs[k] for k in self._kwarg_keys}

        def _flat_listed_components(self) -> Generator["Recipe", None, None]:
            for c in self.component_list():
                if isinstance(c, Recipe):
                    yield c
                else:
                    yield from c

        def _flat_mapped_components(self) -> Generator["Recipe", None, None]:
            for c in self.component_map().values():
                if isinstance(c, Recipe):
                    yield c
                else:
                    yield from c

        def components(self) -> Generator["Recipe", None, None]:
            yield from self._flat_listed_components()
            yield from self._flat_mapped_components()

    @classmethod
    def scan(cls, args: Iterable[Any], kwargs: dict[str, Any]) -> Scanner:
        """
        Scan the given arguments for recipes, and return a tuple of offsets
        and keys where the recipes or recipe lists were found.

        Iterators are copied and instances of generators are expanded.

        Returns the scan results, consisting of a new args, kwargs, and lists
        of offsets and keys where recipes or recipe lists can be found.
        """

        scanner = Recipe.Scanner()

        for i, arg in enumerate(args):
            scanner.scan(arg, offset=i)

        for k, arg in kwargs.items():
            scanner.scan(arg, key=k)

        return scanner

    @classmethod
    def flat(
        cls, recipes: Iterable["Recipe"], visited: Optional[set["Recipe"]] = None
    ) -> Generator["Recipe", None, None]:
        visited = visited or set()
        for recipe in recipes:
            if recipe not in visited:
                visited.add(recipe)
                yield recipe
            yield from cls.flat(recipe.children, visited)

    def __init__(
        self,
        component_list: ComponentIterable = [],
        component_map: MappedComponents = {},
        *,
        as_user: Optional[str] = None,
        deps: Iterable["Recipe"] = [],
        docs: Optional[str] = None,
        fmt: Format = Format(),
        keep=False,
        memoize=False,
        name="(nameless)",
        parent: Optional["Recipe"] = None,
        setup: Optional["Recipe"] = None,
        sigil: Optional[FormatF] = None,
        static_files: Iterable[PathSpec] = [],
        cleanup_files: Iterable[PathSpec] = [],
        sync=False,
        target: Optional[PathSpec] = None,
    ):
        self.component_list = [*component_list]
        self.component_map = component_map
        self.id = uuid.uuid4()

        self._callsign = ""
        self._children: list["Recipe"] = []
        self._deps = [*deps]
        self._parent: Optional["Recipe"] = None
        self._target = None if target is None else Path(target)

        self.as_user = as_user
        self.docs = docs
        self.fmt = fmt
        self.keep = keep
        self.memoize = memoize
        self.name = name
        self.setup = setup
        self.static_files = [
            Path(s) for s in static_files if target is None or Path(s) != Path(target)
        ]
        self.cleanup_files = [
            Path(s) for s in cleanup_files if target is None or Path(s) != Path(target)
        ]
        self.sync = sync

        if parent:
            self.parent = parent

        if sigil:
            self.fmt = Recipe.FormatOverride(self.fmt, sigil=sigil)

        self.lock = asyncio.Lock()
        self.saved_result = None

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return f"<{self.callsign}>"

    def __iter__(self):
        yield from self.components()

    def arg(self, name: str | int):
        if isinstance(name, int):
            return self.component_list[name]
        elif isinstance(name, str):
            return self.component_map[name]
        else:
            raise ValueError(f"Invalid arg type: {type(name)}")

    @property
    def target(self) -> Path:
        assert self._target is not None, "There is no target."
        return self._target

    @target.setter
    def target(self, path: Path):
        self._target = path

    def has_target(self):
        return self._target is not None

    @property
    def parent(self) -> "Recipe":
        assert self._parent, "Recipe has no parent."
        return self._parent

    @parent.setter
    def parent(self, recipe: "Recipe"):
        self._parent = recipe
        if self not in self._parent._children:
            self._parent._children.append(self)

    @property
    def children(self) -> Iterable["Recipe"]:
        return [*self._children]

    @property
    def callsign(self) -> str:
        if not self._callsign:
            return self.sigil()
        return self._callsign

    @callsign.setter
    def callsign(self, sign: str):
        self._callsign = sign

    def has_parent(self):
        return self._parent is not None

    def sigil(self) -> str:
        return self.fmt.sigil(self)

    def log(self, event_name: str, data: Any = None):
        bus = EventBus.get()
        event = Event(event_name, self, data)
        bus.send(event)

    def error(self, msg) -> RuntimeError:
        exc = RuntimeError(msg)
        self.log(Events.ERROR, exc)
        return exc

    def has_components(self):
        try:
            next(self.components())
            return True

        except StopIteration:
            return False

    def components(self) -> Generator["Recipe", None, None]:
        yield from self.component_list
        for c in self.component_map.values():
            if isinstance(c, Recipe):
                yield c
            else:
                yield from c

    def composite_error(self, exceptions: Iterable[Exception], msg: str):
        exc = CompositeError(exceptions, msg)
        self.log(Events.ERROR, exc)
        return exc

    def age(self, ref: datetime) -> timedelta:
        if self.has_target() and self.target.exists():
            return ref - datetime.fromtimestamp(self.target.stat().st_mtime)
        if self.has_target() and self.target.is_symlink():
            return timedelta.min
        return timedelta.min

    def static_files_age(self, ref: datetime) -> timedelta:
        if not self.static_files:
            return timedelta.max
        else:
            return min(
                ref - datetime.fromtimestamp(f.stat().st_mtime)
                for f in self.static_files
            )

    def components_age(self, ref: datetime) -> timedelta:
        if not self.has_components():
            return timedelta.max
        else:
            return min(max(c.age(ref), c.inputs_age(ref)) for c in self.components())

    def add_dependency(self, dep: "Recipe"):
        assert isinstance(dep, Recipe), f"Value `{dep}` is not a recipe."
        self._deps.append(dep)
        for component in self.components():
            component.add_dependency(dep)

    def dependencies(self) -> Generator["Recipe", None, None]:
        yield from self._deps
        if self.has_parent():
            yield from self.parent.dependencies()

    def dependencies_age(self, ref: datetime) -> timedelta:
        if not self.has_components():
            return timedelta.max
        else:
            return min(
                max(dep.age(ref), dep.inputs_age(ref)) for dep in self.dependencies()
            )

    def inputs_age(self, ref: datetime) -> timedelta:
        return min(
            self.static_files_age(ref),
            self.components_age(ref),
            self.dependencies_age(ref),
        )

    def components_results(self) -> tuple[list[Any], dict[str, Any]]:
        results = [c.result() for c in self.component_list]
        mapped_results = {}

        for k, c in self.component_map.items():
            if isinstance(c, Recipe):
                mapped_results[k] = c.result()
            else:
                mapped_results[k] = [r.result() for r in c]

        return results, mapped_results

    def done(self) -> bool:
        if self.has_target():
            if self.target.is_symlink():
                return True
            return self.target.exists() and not self.outdated(datetime.now())
        return self.saved_result is not None

    def components_done(self) -> bool:
        return all(c.done() for c in self.components())

    def outdated(self, ref: datetime) -> bool:
        if self.has_target() and self.target.is_symlink():
            return False
        return self.age(ref) > self.inputs_age(ref)

    async def clean(self):
        remove_paths(*self.cleanup_files, as_user=self.as_user)

        if (
            not self.has_target()
            or (not self.target.exists() and not self.target.is_symlink())
            or self.keep
        ):
            return

        try:
            remove_paths(self.target, as_user=self.as_user)

        except Exception as e:
            raise self.error("Failed to clean target.") from e

        self.saved_result = None
        self.log(Events.CLEAN, self.target)

    async def clean_components(self, recursive=False):
        recipes = [*self.components()]

        if recursive:
            recipes.extend(self._deps)
            results = await asyncio.gather(
                *[c.clean() for c in recipes],
                *[c.clean_components(recursive=True) for c in recipes],
            )
        else:
            results = await asyncio.gather(
                *(c.clean() for c in recipes), return_exceptions=True
            )
        exceptions = [e for e in results if isinstance(e, Exception)]
        if exceptions:
            raise self.composite_error(
                exceptions, "Failed to clean one or more components."
            )

    async def make_dependencies(self):
        recipes = [*self.dependencies()]
        if self.sync:
            for c in recipes:
                try:
                    await c()
                except Exception as e:
                    raise self.error("Failed to make a dependency.") from e
        else:
            results = await asyncio.gather(
                *(c() for c in recipes), return_exceptions=True
            )
            exceptions = [e for e in results if isinstance(e, Exception)]
            if exceptions:
                raise self.composite_error(
                    exceptions, "Failed to make one or more dependencies."
                )

    async def make_components(self) -> tuple[list[Any], dict[str, Any]]:
        recipes = [*self.components()]
        if self.sync:
            results = []
            for c in recipes:
                try:
                    results.append(await c())

                except Exception as e:
                    raise self.error("Failed to make component.") from e

            return self.components_results()

        else:
            results = await asyncio.gather(
                *(c() for c in recipes), return_exceptions=True
            )
            exceptions = [e for e in results if isinstance(e, Exception)]
            if exceptions:
                raise self.composite_error(
                    exceptions, "Failed to make one or more components."
                )
            return self.components_results()

    async def make(self):
        return [r.result() for r in self.components()]

    def result(self):
        if self.done() and self.has_target():
            return self.target
        if self.saved_result is None:
            raise ValueError("Recipe result has not yet been recorded.")
        return self.saved_result

    def result_or(self, other):
        try:
            return self.result()
        except ValueError:
            return other

    def rel_target(self):
        try:
            return self.target.relative_to(Path.cwd())
        except ValueError:
            return self.target

    def rel_target_or(self, other):
        if self._target is None:
            return other
        return self.rel_target()

    def exe_target(self) -> str:
        rel_target = self.rel_target()
        if not rel_target.is_absolute() and not rel_target.parent:
            target = Path.cwd() / rel_target
            if target.is_file() and os.access(target, os.X_OK):
                return f"./{str(self.rel_target)}"
        return str(rel_target)

    def target_or(self, other):
        if self._target is None:
            return other
        return self.target

    async def _resolve(self):
        await self.make_dependencies()

        self.log(Events.START)
        await self.make_components()
        result = await self.make()

        if is_iterable(result):
            scanner = Recipe.Scanner()
            scanner.scan_params(*result)
            while scanner.has_recipes():
                await scanner.gather_all()
            result = scanner.args(pass_mode=Recipe.PassMode.RESULTS)

        elif isinstance(result, Recipe):
            result = await result()

        if self.has_target():
            assert isinstance(
                result, str | Path
            ), "Recipe declared a file target, but the result was not a string or Path object."

            result = Path(result)
            assert (
                result.resolve() == self.target.resolve()
            ), f"Recipe declared a file target, but the result path differs: {result} != {self.target}."

        self.saved_result = result

        if not self.done():
            self.saved_result = None
            raise self.error("Recipe make() didn't complete successfully.")

        return result

    async def __call__(self):
        async with self.lock:
            if self.done():
                if self.has_target():
                    return self.target
                elif self.memoize:
                    return self.saved_result

            try:
                Recipe.active.add(self)

                if self.setup is not None:
                    await self.setup()

                result = await self._resolve()
                self.log(Events.SUCCESS)
                return result

            except Exception as e:
                self.log(Events.FAIL, e)
                raise BuildError(self, str(e)) from e

            finally:
                Recipe.active.remove(self)


# --------------------------------------------------------------------
class Lambda(Recipe):
    def __init__(
        self,
        f: Callable,
        lambda_args: list[Any],
        lambda_kwargs: dict[str, Any],
        docs: Optional[str] = None,
        pass_mode=Recipe.PassMode.RESULTS,
        target_param=Recipe.DEFAULT_TARGET_PARAM,
        **kwargs,
    ):
        if "name" not in kwargs:
            kwargs = {**kwargs, "name": f.__name__}

        scanner = Recipe.scan(lambda_args, lambda_kwargs)
        sig = inspect.signature(f)
        self.bound_args = sig.bind(*lambda_args, **lambda_kwargs)
        target = self.bound_args.arguments.get(target_param, None)

        super().__init__(
            scanner.component_list(),
            scanner.component_map(),
            static_files=scanner.paths(),
            target=target,
            docs=docs or f.__doc__,
            **kwargs,
        )
        self.f = f
        self.pass_mode = pass_mode
        self.scanner = scanner

    def arg(self, name: str | int):
        if isinstance(name, str):
            return self.bound_args.arguments.get(name, None)
        else:
            return [*self.bound_args.arguments.values()][name]

    async def make(self):
        return await async_wrap(
            self.f,
            *self.scanner.args(self.pass_mode),
            **self.scanner.kwargs(self.pass_mode),
        )


# --------------------------------------------------------------------
def _inject_dependency(recipe: Recipe, dep):
    if is_iterable(dep):
        for d in dep:
            _inject_dependency(recipe, d)
    else:
        recipe.add_dependency(dep)


# --------------------------------------------------------------------
def _inject_dependencies(
    recipe: Recipe, deps: Iterable[str], bound_args: inspect.BoundArguments
):
    for dep in deps:
        dobj = bound_args.arguments.get(dep)
        _inject_dependency(recipe, dobj)


# --------------------------------------------------------------------
def recipe(
    name_or_f: Optional[str | Callable] = None,
    *,
    dep: Optional[str | Iterable[str]] = None,
    docs: Optional[str] = None,
    factory=False,
    fmt: Optional[Recipe.Format] = None,
    keep=False,
    memoize=False,
    sigil: Optional[FormatF] = None,
    sync=False,
    cleanup: Optional[str | Iterable[str]] = None,
):
    """
    Decorator for a function that defines a recipe template.

    The function is meant to be a recipe implementation method.  The
    parameters eventually passed to the method depend on whether the
    parameters are recipes or plain values.  Each recipe parameter has its
    result passed, whereas plain values are passed through unmodified.

    Can be called with no parameters.  In this mode, the name is assumed
    to be the name of the decorated function and all other parameters
    are set to their defaults.

    If `factory` is true, the function is a recipe factory that returns one
    or more recipes and the values passed to it are the recipe objects
    named.

    If `name` is provided, it is used as the name of the recipe.  Otherwise,
    the name of the recipe is inferred to be the name of the decorated
    function.

    Otherwise, the function is interpreted as a recipe implementation
    method and the values passed to it when it is eventually called
    are the result values of its dependencies.

    If `sync` is provided, the resulting recipe's dependencies are resolved
    synchronously.  Otherwise, they are resolved asynchronously using
    asyncio.gather().

    If `memoize` is provided, the recipe result is not recalculated by
    other dependencies, and the recipe implementation will only be
    evaluated once.

    If `cleanup` is provided, the referenced path(s) will additionally
    be removed when the resulting task is cleaned.
    """

    name = None if callable(name_or_f) else name_or_f

    def wrapper(f):
        @MethodAttributes.wraps(f)
        def target_wrapper(*args, **kwargs):
            truename = name or f.__name__
            scanner = Recipe.scan(args, kwargs)
            cleanup_files = [] if cleanup is None else list_or_delim(cleanup)
            cleanup_paths = [Path(s) for s in cleanup_files]

            if factory:
                if inspect.iscoroutinefunction(f):
                    raise ValueError(
                        "Recipe factories should not be coroutines.  You should define asynchronous behavior in recipes and return these from recipe factories and target definitions instead."
                    )

                result = f(
                    *scanner.args(Recipe.PassMode.NORMAL),
                    **scanner.kwargs(Recipe.PassMode.NORMAL),
                )

                if is_iterable(result):
                    result = Recipe(
                        [*result],
                        docs=docs,
                        fmt=fmt or Recipe.Format(),
                        keep=keep,
                        memoize=memoize,
                        name=truename,
                        sync=sync,
                        cleanup_files=cleanup_paths,
                    )
                elif result is None:
                    result = Recipe([], docs=docs, name=truename)
                else:
                    result = cast(Recipe, result)

                    result.docs = docs
                    result.fmt = fmt or result.fmt
                    result.keep = keep
                    result.memoize = memoize
                    result.name = truename
                    result.sync = sync
                    result.cleanup_files = cleanup_paths

            else:
                result = Lambda(
                    f,
                    [*args],
                    {**kwargs},
                    docs=docs,
                    fmt=fmt or Recipe.Format(),
                    keep=keep,
                    memoize=memoize,
                    name=truename,
                    sync=sync,
                    cleanup_files=cleanup_paths,
                )

            if sigil:
                result.fmt = Recipe.FormatOverride(result.fmt, sigil=sigil)

            _inject_dependencies(
                result,
                [] if dep is None else list_or_delim(dep),
                scanner.bind(f, Recipe.PassMode.NORMAL),
            )

            return result

        return target_wrapper

    if callable(name_or_f):
        return no_type_check(wrapper(name_or_f))

    return no_type_check(cast(Callable[[Callable], Callable], wrapper))
