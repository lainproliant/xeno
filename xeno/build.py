# --------------------------------------------------------------------
# build.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Friday March 17, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
from argparse import ArgumentParser
from typing import Any, Callable, Optional, cast, no_type_check

# --------------------------------------------------------------------
from xeno.async_injector import AsyncInjector
from xeno.attributes import MethodAttributes
from xeno.decorators import named
from xeno.events import EventBus
from xeno.recipe import Events, Lambda, Recipe
from xeno.utils import async_map, is_iterable


# --------------------------------------------------------------------
class Config:
    class Mode:
        BUILD = "build"
        REBUILD = "rebuild"
        CLEAN = "clean"
        LIST = "list"
        TREE = "tree"

    class CleanupMode:
        SHALLOW = "shallow"
        RECURSIVE = "recursive"

    def __init__(self, name):
        self.name = name
        self.mode = self.Mode.BUILD
        self.cleanup_mode = self.CleanupMode.RECURSIVE
        self.debug = False
        self.force_color = False
        self.targets: list[str] = []
        self.max_shells: Optional[int] = None

    def _argparser(self):
        parser = ArgumentParser(description=self.name, add_help=True)
        parser.add_argument("targets", nargs="*")
        parser.add_argument(
            "--clean",
            "-c",
            dest="mode",
            action="store_const",
            const=self.Mode.CLEAN,
            help="Clean the specified targets and all of their inputs.",
        )
        parser.add_argument(
            "--rebuild",
            "-R",
            dest="mode",
            action="store_const",
            const=self.Mode.REBUILD,
            help="Clean the specified targets, then rebuild them.",
        )
        parser.add_argument(
            "--verbose",
            "-v",
            action="count",
            help="Print stdout (-v) and/or stderr (-vv) for live running commands.",
        )
        parser.add_argument(
            "--list",
            "-l",
            dest="mode",
            action="store_const",
            const=self.Mode.LIST,
            help="List all defined targets.",
        )
        parser.add_argument(
            "--debug",
            "-D",
            action="store_true",
            help="Print stack traces and other diagnostic info.",
        )
        parser.add_argument(
            "--force-color",
            action="store_true",
            help="Force color output to non-tty.  Useful for IDEs.",
        )
        parser.add_argument(
            "--max",
            "-m",
            dest="max_shells",
            type=int,
            default=None,
            help="Set the max number of simultaneous live commands.",
        )
        parser.set_defaults(mode=self.Mode.BUILD)
        return parser

    def parse_args(self, *args):
        self._argparser().parse_args(args, namespace=self)
        return self


# --------------------------------------------------------------------
class Engine:
    class Attributes:
        TARGET = "xeno.build.target"
        DEFAULT = "xeno.build.default"

    def __init__(self, name="Xeno v5 Build Engine"):
        self.name = name
        self.injector = AsyncInjector()

    def targets(self) -> list[str]:
        return [
            k
            for k, _ in self.injector.scan_resources(
                lambda _, v: v.check(self.Attributes.TARGET)
            )
        ]

    def default_target(self) -> Optional[str]:
        results = [
            k
            for k, _ in self.injector.scan_resources(
                lambda _, v: v.check(self.Attributes.DEFAULT)
            )
        ]
        assert len(results) <= 1, "More than one default target specified."
        return results[0] if results else None

    def provide(self, *args, **kwargs):
        self.injector.provide(*args, **{**kwargs, "is_singleton": True})

    def recipe(
        self,
        name_or_f: Optional[str | Callable] = None,
        *,
        factory=False,
        sync=False,
        memoize=False,
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
        """

        name = None if callable(name_or_f) else name_or_f

        def wrapper(f):
            @MethodAttributes.wraps(f)
            def target_wrapper(*args, **kwargs):
                truename = name or f.__name__
                if factory:
                    result = f(*args, **kwargs)
                    if is_iterable(result):
                        result = Recipe(
                            [*result],
                            name=truename,
                            sync=sync,
                            memoize=memoize,
                        )
                    else:
                        result = cast(Recipe, result)

                    result.sync = sync
                    result.memoize = memoize
                    result.name = truename
                    return result

                return Lambda(
                    f,
                    [*args],
                    {**kwargs},
                    name=truename,
                    sync=sync,
                    memoize=memoize,
                )

            return target_wrapper

        if callable(name_or_f):
            return no_type_check(wrapper(name_or_f))

        return no_type_check(cast(Callable[[Callable], Callable], wrapper))

    def target(
        self,
        name_or_f: Optional[str | Callable] = None,
        *,
        default=False,
        sync=False,
    ):
        """
        Decorator for defining a target recipe for a build.

        Can be called with no parameters.  In this mode, the name is assumed
        to be the name of the decorated function and all other parameters
        are set to their defaults.

        If `default` is True, the target will be the default target
        when no target is specified at build time.  This method will
        throw ValueError if another target has already been specified
        as the default target.

        See `doc(xeno.build.Engine.recipe)` for info about the other params.
        """

        name = None if callable(name_or_f) else name_or_f

        def wrapper(f):
            target_wrapper = cast(
                Recipe, self.recipe(name, factory=True, sync=sync, memoize=True)(f)
            )
            attrs = MethodAttributes.for_method(target_wrapper, True, True)
            assert attrs is not None
            attrs.put(self.Attributes.TARGET)
            if default:
                attrs.put(self.Attributes.DEFAULT)
            if name is not None:
                target_wrapper = named(name)(target_wrapper)
            self.provide(target_wrapper)
            return target_wrapper

        if callable(name_or_f):
            return wrapper(name_or_f)

        return wrapper

    def _on_recipe_start(self, event):
        print(f"LRS-DEBUG: start: {event.context.name}")

    def _on_recipe_info(self, event):
        print(f"LRS-DEBUG: start: {event.context.name}")

    def _on_recipe_clean(self, event):
        print(f"LRS-DEBUG: clean: {event.context.name}")

    def _on_recipe_error(self, event):
        print(f"LRS-DEBUG: error: {event.context.name}")

    def _on_recipe_success(self, event):
        print(f"LRS-DEBUG: success: {event.context.name}")

    async def build_async(self, *argv) -> list[Any]:
        bus = EventBus.get()
        bus.subscribe(Events.START, self._on_recipe_start)
        bus.subscribe(Events.INFO, self._on_recipe_info)
        bus.subscribe(Events.CLEAN, self._on_recipe_clean)
        bus.subscribe(Events.ERROR, self._on_recipe_error)
        bus.subscribe(Events.SUCCESS, self._on_recipe_success)

        config = Config("Xeno Build Engine v5").parse_args(*argv)
        if not config.targets:
            default_target = self.default_target()
            if default_target is not None:
                config.targets = [default_target]
            else:
                raise ValueError(
                    "No target specified and no default target defined."
                )

        targets = await asyncio.gather(
            *[
                async_map(name, self.injector.require_async(name))
                for name in config.targets
            ]
        )

        for name, target in targets:
            assert isinstance(
                target, Recipe
            ), f"Target `{name}` did not yield a recipe."

        scan = Recipe.Scanner()
        scan.scan_args(*[v for _, v in targets])
        while scan.has_recipes():
            await scan.gather_all()

        bus.shutdown()
        return scan.args(Recipe.PassMode.RESULTS)

    async def _build_loop(self, bus, *argv):
        result, _ = await asyncio.gather(self.build_async(*argv), bus.run())
        return result

    def build(self, *argv):
        with EventBus.session():
            bus = EventBus.get()
            return asyncio.run(self._build_loop(bus, *argv))
