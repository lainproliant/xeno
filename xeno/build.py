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
from typing import Optional, cast

# --------------------------------------------------------------------
from xeno.async_injector import AsyncInjector
from xeno.attributes import MethodAttributes
from xeno.decorators import named
from xeno.events import EventBus
from xeno.recipe import Events, Lambda, Recipe


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

    def target(
        self,
        name: Optional[str] = None,
        *,
        factory=False,
        multi=False,
        default=False,
        sync=False,
        memoize=False,
    ):
        """
        Decorator for defining a target recipe for a build.

        If `factory` or `multi` are true, the function is a recipe factory
        that returns one or more recipes and the values passed to it
        are the recipe objects named.

        If `name` is provided, it is used as the name of the recipe.  Otherwise,
        the name of the recipe is inferred to be the name of the decorated
        function.

        Otherwise, the function is interpreted as a recipe implementation
        method and the values passed to it when it is eventually called
        are the result values of its dependencies.

        If `default` is True, the target will be the default target
        when no target is specified at build time.  This method will
        throw ValueError if another target has already been specified
        as the default target.
        """

        def wrapper(f):
            @MethodAttributes.wraps(f)
            async def target_wrapper(*args, **kwargs):
                if factory or multi:
                    if multi:
                        return Recipe(f(*args, **kwargs), sync=sync, memoize=memoize)
                    else:
                        result = cast(Recipe, f(*args, **kwargs))
                        result.sync = sync
                        result.memoize = memoize
                        return result

                return Lambda(
                    f,
                    kwargs,
                    pflags=Lambda.KWARGS & Lambda.RESULTS,
                    sync=sync,
                    memoize=memoize,
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

        return wrapper

    def _on_recipe_clean(self, event):
        print(f"LRS-DEBUG: clean: {event}")

    def _on_recipe_error(self, event):
        print(f"LRS-DEBUG: error: {event}")

    def _on_recipe_success(self, event):
        print(f"LRS-DEBUG: success: {event}")

    def build(self, *argv):
        with EventBus.session():
            bus = EventBus.get()
            bus.subscribe(Events.CLEAN, self._on_recipe_clean)
            bus.subscribe(Events.ERROR, self._on_recipe_error)
            bus.subscribe(Events.SUCCESS, self._on_recipe_success)

            asyncio.run(bus.run())
