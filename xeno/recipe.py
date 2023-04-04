# --------------------------------------------------------------------
# recipe.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday March 9, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
import shutil
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generator, Iterable, Optional

from xeno.events import Event, EventBus
from xeno.shell import Shell
from xeno.utils import async_map, async_vwrap, async_wrap, is_iterable


# --------------------------------------------------------------------
class Events:
    CLEAN = "clean"
    DEBUG = "debug"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    START = "start"
    SUCCESS = "success"


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


# --------------------------------------------------------------------
class Recipe:
    class PassMode(Enum):
        NORMAL = 0
        RESULTS = 1

    class Scanner:
        def __init__(self):
            self._args: list[Any] = []
            self._kwargs: dict[str, Any] = {}
            self._arg_offsets: list[int] = []
            self._kwarg_keys: list[str] = []

        def _scan_one(self, arg) -> tuple[Any, bool]:
            if isinstance(arg, Recipe):
                return arg, True

            if is_iterable(arg):
                arg = [*arg]
                if all(isinstance(x, Recipe) for x in arg):
                    return arg, True

            return arg, False

        def has_recipes(self):
            return self._arg_offsets or self._kwarg_keys

        async def gather_args(self):
            """
            Await resolution of recipes in args and update args with their results.
            """
            results = await asyncio.gather(
                *[v() if isinstance(v, Recipe) else async_vwrap(v) for v in self._args]
            )
            self.scan_args(*results)

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
            self.scan_kwargs(**results)

        def gather_all(self):
            """
            Await resolution of recipes in args and kwargs and update both with
            their results.
            """

            return asyncio.gather(self.gather_args(), self.gather_kwargs())

        def scan_args(self, *args):
            self._args.clear()
            self._arg_offsets.clear()
            for i, arg in enumerate(args):
                self.scan(arg, offset=i)

        def scan_kwargs(self, **kwargs):
            self._kwargs.clear()
            self._kwarg_keys.clear()
            for k, arg in kwargs.items():
                self.scan(arg, key=k)

        def scan_args_kwargs(self, *args, **kwargs):
            self.scan_args(*args)
            self.scan_kwargs(**kwargs)

        def scan(
            self, arg, offset: Optional[int] = None, key: Optional[str] = None
        ) -> bool:
            arg, is_recipe = self._scan_one(arg)

            if offset is not None:
                self._args.append(arg)
                if is_recipe:
                    self._arg_offsets.append(offset)

            elif key is not None:
                self._kwargs[key] = arg
                if is_recipe:
                    self._kwarg_keys.append(key)

            return is_recipe

        def args(self, pass_mode: "Recipe.PassMode") -> list[Any]:
            if pass_mode == Recipe.PassMode.NORMAL:
                return self._args
            results = [*self._args]
            for offset in self._arg_offsets:
                value = results[offset]
                if is_iterable(value):
                    results[offset] = [r.result() for r in value]
                else:
                    results[offset] = value.result()
            return results

        def kwargs(self, pass_mode: "Recipe.PassMode") -> dict[str, Any]:
            if pass_mode == Recipe.PassMode.NORMAL:
                return self._kwargs
            results = {**self._kwargs}
            for key in self._kwarg_keys:
                value = results[key]
                if is_iterable(value):
                    results[key] = [r.result() for r in value]
                else:
                    results[key] = value.result()
            return results

        def component_list(self) -> ListedComponents:
            return [self._args[x] for x in self._arg_offsets]

        def component_map(self) -> MappedComponents:
            return {k: self._kwargs[k] for k in self._kwarg_keys}

    def __init__(
        self,
        component_list: ListedComponents = [],
        component_map: MappedComponents = {},
        *,
        setup: Optional["Recipe"] = None,
        name="Nameless Recipe",
        sync=False,
        memoize=False,
    ):
        self.component_list = component_list
        self.component_map = component_map

        self.lock = asyncio.Lock()
        self.setup = setup
        self.name = name
        self.sync = sync
        self.memoize = memoize
        self.saved_result = None

    @staticmethod
    def scan(args: list[Any], kwargs: dict[str, Any]) -> Scanner:
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

    def _contextualize(self, s: str) -> str:
        return f"(for {self}) {s}"

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

    def age(self, _: datetime) -> timedelta:
        return timedelta.max

    def component_age(self, ref: datetime) -> timedelta:
        if not self.has_components():
            return timedelta.max
        else:
            return min(min(c.age(ref), c.component_age(ref)) for c in self.components())

    def component_results(self) -> tuple[list[Any], dict[str, Any]]:
        results = [c.result() for c in self.component_list]
        mapped_results = {}

        for k, c in self.component_map.items():
            if isinstance(c, Recipe):
                mapped_results[k] = c.result()
            else:
                mapped_results[k] = [r.result() for r in c]

        return results, mapped_results

    def done(self) -> bool:
        return self.saved_result is not None

    def components_done(self) -> bool:
        return all(c.done() for c in self.components())

    def outdated(self, ref: datetime) -> bool:
        return self.age(ref) <= self.component_age(ref)

    async def clean(self):
        pass

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

            return self.component_results()

        else:
            results = await asyncio.gather(
                *(c() for c in self.components()), return_exceptions=True
            )
            exceptions = [e for e in results if isinstance(e, Exception)]
            if exceptions:
                raise self.composite_error(
                    exceptions, "Failed to make one or more components."
                )
            return self.component_results()

    async def make(self):
        return True

    def result(self):
        if self.saved_result is None:
            raise ValueError("Recipe result has not yet been recorded.")
        return self.saved_result

    async def __call__(self):
        async with self.lock:
            if self.memoize and self.saved_result is not None:
                return self.saved_result

            if self.setup is not None:
                try:
                    await self.setup()

                except Exception as e:
                    raise self.error("Setup method failed.") from e

            self.log(Events.START)

            await self.make_components()
            result = await self.make()
            scanner = Recipe.Scanner()

            if scanner.scan(result):
                self.log(
                    Events.WARNING,
                    "Recipe make() returned one or more other recipes, it should probably be a factory.",
                )

            if result is None:
                raise self.error("Recipe make() didn't return a value.")

            self.saved_result = result

            if not self.done():
                self.saved_result = None
                raise self.error("Recipe make() didn't complete successfully.")

            self.log(Events.SUCCESS)

            return result


# --------------------------------------------------------------------
class FileRecipe(Recipe):
    def __init__(
        self,
        target: str | Path,
        component_list: ListedComponents = [],
        component_map: MappedComponents = {},
        *,
        static=False,
        user: Optional["str"] = None,
        **kwargs,
    ):
        assert not (
            static and (component_list or component_map)
        ), "Static files can't have components."
        super().__init__(component_list, component_map, **kwargs)
        self.target = Path(target)
        self.static = static
        self.user = user

    def age(self, ref: datetime) -> timedelta:
        if not self.target.exists():
            return timedelta.max
        return ref - datetime.fromtimestamp(self.target.stat().st_mtime)

    def done(self):
        return self.target.exists()

    async def clean(self):
        if self.static or not self.target.exists():
            return
        try:
            if self.user:
                result = Shell().interact_as(
                    self.user, ["rm", "-rf", str(self.target.absolute())]
                )
                if result != 0:
                    raise RuntimeError(
                        f"Failed to delete `f{self.target}` as `f{self.user}`."
                    )
            else:
                if self.target.is_dir():
                    shutil.rmtree(self.target)
                else:
                    self.target.unlink()

        except Exception as e:
            raise self.error("Failed to clean.") from e

        self.log(Events.CLEAN, self.target)

    async def make(self):
        return self.target


# --------------------------------------------------------------------
class Lambda(Recipe):
    def __init__(
        self,
        f: Callable,
        lambda_args: list[Any],
        lambda_kwargs: dict[str, Any],
        pass_mode=Recipe.PassMode.RESULTS,
        **kwargs,
    ):
        if "name" not in kwargs:
            kwargs = {**kwargs, "name": f.__name__}

        scanner = Recipe.scan(lambda_args, lambda_kwargs)

        super().__init__(scanner.component_list(), scanner.component_map(), **kwargs)
        self.f = f
        self.pass_mode = pass_mode
        self.scanner = scanner

    async def make(self):
        return await async_wrap(
            self.f,
            *self.scanner.args(self.pass_mode),
            **self.scanner.kwargs(self.pass_mode),
        )
