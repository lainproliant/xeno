# --------------------------------------------------------------------
# recipe.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday March 9, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
import inspect
import shutil
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generator, Iterable, Optional

from xeno.events import Event, EventBus
from xeno.shell import PathSpec, Shell
from xeno.utils import async_map, async_vwrap, async_wrap, is_iterable


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


# --------------------------------------------------------------------
class BuildError(Exception):
    pass


# --------------------------------------------------------------------
class CompositeError(Exception):
    def __init__(
        self, exceptions: Iterable[Exception], msg: str = "Multiple errors occurred."
    ):
        self.exceptions = list(exceptions)
        super().__init__(self._compose_message(msg))

    def _compose_message(self, msg: str):
        sb = []
        sb.append(msg)

        for exc in self.exceptions:
            for line in str(exc).strip().split("\n"):
                sb.append("\t" + line)
        return "\n".join(sb)


# --------------------------------------------------------------------
ListedComponents = Iterable["Recipe"]
MappedComponents = dict[str, "Recipe" | Iterable["Recipe"]]
FormatF = Callable[["Recipe"], str]


# --------------------------------------------------------------------
class Recipe:
    DEFAULT_TARGET_PARAM = "out"
    SIGIL_TARGET_SEPARATOR = "→ "
    START_SYMBOL = "⚙"
    OK_SYMBOL = "✓"
    FAIL_SYMBOL = "✗"
    WARNING_SYMBOL = "⚠"

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

        def _scan_one(self, arg) -> tuple[Any, "Recipe.ParamType"]:
            if isinstance(arg, Recipe):
                return arg, Recipe.ParamType.RECIPE

            if is_iterable(arg):
                arg = [*arg]
                if all(isinstance(x, Recipe) for x in arg):
                    return arg, Recipe.ParamType.RECIPE
                if all(isinstance(x, Path) for x in arg):
                    return arg, Recipe.ParamType.PATH

            if isinstance(arg, Path):
                return arg, Recipe.ParamType.PATH

            return arg, Recipe.ParamType.NORMAL

        def has_recipes(self):
            return self._arg_offsets or self._kwarg_keys

        async def gather_args(self):
            """
            Await resolution of recipes in args and update args with their results.
            """
            results = await asyncio.gather(
                *[v() if isinstance(v, Recipe) else async_vwrap(v) for v in self._args]
            )
            for n in self._arg_offsets:
                if isinstance(results[n], Recipe):
                    results[n].configure(self._args[n])
            self.scan_params(*results)

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
            for k in self._kwarg_keys:
                if isinstance(results[k], Recipe):
                    results[k].configure(self._kwargs[k])
            self.scan_params(**results)

        def gather_all(self):
            """
            Await resolution of recipes in args and kwargs and update both with
            their results.
            """

            return asyncio.gather(self.gather_args(), self.gather_kwargs())

        def scan_params(self, *args, **kwargs):
            self._args.clear()
            self._arg_offsets.clear()
            self._kwargs.clear()
            self._kwarg_keys.clear()
            self._paths.clear()

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

        def components(self) -> Generator["Recipe", None, None]:
            yield from self.component_list()
            for c in self.component_map().values():
                if isinstance(c, Recipe):
                    yield c
                else:
                    yield from c

    @staticmethod
    def scan(args: Iterable[Any], kwargs: dict[str, Any]) -> Scanner:
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

    @staticmethod
    def sigil_format(recipe: "Recipe") -> str:
        if recipe.target is not None:
            return f"{recipe.name}{recipe.SIGIL_TARGET_SEPARATOR}{recipe.target.name}"
        return recipe.name

    def __init__(
        self,
        component_list: ListedComponents = [],
        component_map: MappedComponents = {},
        *,
        as_user: Optional[str] = None,
        clean_f: Optional[FormatF] = None,
        fail_f: Optional[FormatF] = None,
        keep=False,
        memoize=False,
        name="(nameless)",
        ok_f: Optional[FormatF] = None,
        setup: Optional["Recipe"] = None,
        sigil: Optional[FormatF] = None,
        start_f: Optional[FormatF] = None,
        static_files: Iterable[PathSpec] = [],
        sync=False,
        target: Optional[PathSpec] = None,
    ):
        self.component_list = component_list
        self.component_map = component_map

        self.as_user = as_user
        self.clean_f: FormatF = clean_f or (
            lambda r: f'cleaned {r.target.name if r.target else ""}'
        )
        self.fail_f: FormatF = fail_f or (lambda _: f"{Recipe.FAIL_SYMBOL} fail")
        self.keep = keep
        self.memoize = memoize
        self.name = name
        self.setup = setup
        self.sigil: FormatF = sigil or Recipe.sigil_format
        self.start_f: FormatF = start_f or (lambda _: f"{Recipe.START_SYMBOL} start")
        self.ok_f: FormatF = ok_f or (lambda _: f"{Recipe.OK_SYMBOL} ok")
        self.static_files = [Path(s) for s in static_files if s != target]
        self.sync = sync
        self.target = None if target is None else Path(target)

        self.lock = asyncio.Lock()
        self.saved_result = None
        self.parent_path: list[str] = []

    def _contextualize(self, s: str) -> str:
        return f"[{self.sigil(self)}] {s}"

    def _configure(self, parent: "Recipe"):
        self.parent_path = parent.path()
        self.memoize = parent.memoize
        for r in self.components():
            r._configure(self)

    def path(self) -> list[str]:
        return [*self.parent_path, self.name]

    def log(self, event_name: str, data: Any = None):
        bus = EventBus.get()
        event = Event(event_name, self, data)
        bus.send(event)

    def error(self, msg) -> RuntimeError:
        exc = RuntimeError(self._contextualize(msg))
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

    def __iter__(self):
        yield from self.components()

    def composite_error(self, exceptions: Iterable[Exception], msg: str):
        exc = CompositeError(exceptions, self._contextualize(msg))
        self.log(Events.ERROR, exc)
        return exc

    def age(self, ref: datetime) -> timedelta:
        if self.target is not None and self.target.exists():
            return ref - datetime.fromtimestamp(self.target.stat().st_mtime)
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
            return min(
                max(c.age(ref), c.components_age(ref)) for c in self.components()
            )

    def inputs_age(self, ref: datetime) -> timedelta:
        return min(self.static_files_age(ref), self.components_age(ref))

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
        if self.target is not None:
            return self.target.exists()
        return self.saved_result is not None

    def components_done(self) -> bool:
        return all(c.done() for c in self.components())

    def outdated(self, ref: datetime) -> bool:
        return self.age(ref) > self.inputs_age(ref)

    async def clean(self):
        if self.target is None or not self.target.exists() or self.keep:
            return

        try:
            if self.as_user:
                result = Shell().interact_as(
                    self.as_user, ["rm", "-rf", str(self.target.absolute())]
                )
                if result != 0:
                    raise RuntimeError(
                        f"Failed to delete `f{self.target}` as `f{self.as_user}`."
                    )
            else:
                if self.target.is_dir():
                    shutil.rmtree(self.target)
                else:
                    self.target.unlink()

        except Exception as e:
            raise self.error("Failed to clean target.") from e

        self.saved_result = None
        self.log(Events.CLEAN, self.target)

    async def clean_components(self):
        results = await asyncio.gather(
            *(c.clean() for c in self.components()), return_exceptions=True
        )
        exceptions = [e for e in results if isinstance(e, Exception)]
        if exceptions:
            raise self.composite_error(
                exceptions, "Failed to clean one or more components."
            )

    async def make_components(self) -> tuple[list[Any], dict[str, Any]]:
        if self.sync:
            results = []
            for c in self.components():
                try:
                    results.append(await c())

                except Exception as e:
                    raise self.error("Failed to make component.") from e

            return self.components_results()

        else:
            results = await asyncio.gather(
                *(c() for c in self.components()), return_exceptions=True
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
        if self.saved_result is None:
            raise ValueError("Recipe result has not yet been recorded.")
        return self.saved_result

    def result_or(self, other):
        try:
            return self.result()
        except ValueError:
            return other

    def target_or(self, other):
        if self.target is None:
            return other
        return self.target

    async def _resolve(self):
        await self.make_components()
        result = await self.make()

        if is_iterable(result):
            scanner = Recipe.Scanner()
            scanner.scan_params(*result)
            while scanner.has_recipes():
                await scanner.gather_all()
            result = scanner.args(pass_mode=Recipe.PassMode.RESULTS)
        else:
            if isinstance(result, Recipe):
                result._configure(self)
                result = await result()

        if self.target is not None:
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
            if self.memoize and self.done() and not self.outdated(datetime.now()):
                return self.saved_result

            try:
                if self.setup is not None:
                    await self.setup()

                self.log(Events.START)
                result = await self._resolve()
                self.log(Events.SUCCESS)
                return result

            except Exception as e:
                self.log(Events.FAIL, e)
                raise BuildError() from e


# --------------------------------------------------------------------
class Lambda(Recipe):
    def __init__(
        self,
        f: Callable,
        lambda_args: list[Any],
        lambda_kwargs: dict[str, Any],
        pass_mode=Recipe.PassMode.RESULTS,
        target_param=Recipe.DEFAULT_TARGET_PARAM,
        **kwargs,
    ):
        if "name" not in kwargs:
            kwargs = {**kwargs, "name": f.__name__}

        scanner = Recipe.scan(lambda_args, lambda_kwargs)
        sig = inspect.signature(f)
        bound_args = sig.bind(*lambda_args, **lambda_kwargs)
        target = bound_args.arguments.get(target_param, None)

        super().__init__(
            scanner.component_list(),
            scanner.component_map(),
            static_files=scanner.paths(),
            target=target,
            **kwargs,
        )
        self.f = f
        self.pass_mode = pass_mode
        self.scanner = scanner

    async def make(self):
        return await async_wrap(
            self.f,
            *self.scanner.args(self.pass_mode),
            **self.scanner.kwargs(self.pass_mode),
        )
