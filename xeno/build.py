# --------------------------------------------------------------------
# build.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Friday March 17, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
import io
from argparse import ArgumentParser
from functools import partial
from typing import Any, Callable, Optional, cast

from xeno.async_injector import AsyncInjector
from xeno.attributes import MethodAttributes
from xeno.color import color
from xeno.cookbook import recipe as base_recipe
from xeno.decorators import named
from xeno.events import Event, EventBus
from xeno.recipe import Events, Recipe, FormatF
from xeno.shell import Environment
from xeno.utils import async_map

# --------------------------------------------------------------------
BusHook = Callable[[EventBus], None]


# --------------------------------------------------------------------
class Config:
    class Mode:
        BUILD = "build"
        REBUILD = "rebuild"
        CLEAN = "clean"
        LIST = "list"
        TREE = "tree"

    class CleanupMode:
        NONE = "none"
        SHALLOW = "shallow"
        RECURSIVE = "recursive"

    def __init__(self, name):
        self.name = name
        self.mode = self.Mode.BUILD
        self.cleanup_mode = self.CleanupMode.NONE
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
            dest="cleanup_mode",
            action="store_const",
            const=self.CleanupMode.RECURSIVE,
            help="Clean the specified targets and all of their inputs.",
        )
        parser.add_argument(
            "--cut",
            "-x",
            dest="cleanup_mode",
            action="store_const",
            const=self.CleanupMode.SHALLOW,
            help="Clean just the specified target leaving inputs intact.",
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
            "--list-tree",
            "-L",
            dest="mode",
            action="store_const",
            const=self.Mode.TREE,
            help="List all defined targets and all subtargets.",
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
        if self.cleanup_mode != Config.CleanupMode.NONE:
            self.mode = Config.Mode.CLEAN
        if self.mode == Config.Mode.REBUILD:
            self.cleanup_mode = Config.CleanupMode.RECURSIVE
        return self


# --------------------------------------------------------------------
class Engine:
    TARGET_SEP = "::"

    class Attributes:
        TARGET = "xeno.build.target"
        DEFAULT = "xeno.build.default"

    def __init__(self, name="Xeno v5 Build Engine"):
        self.name = name
        self.bus_hooks: list[BusHook] = list()
        self.env = Environment.context()
        self.injector = AsyncInjector()

    def add_hook(self, hook: BusHook):
        self.bus_hooks.append(hook)

    async def root_targets(self) -> list[tuple[str, Recipe]]:
        root_names = [
            k
            for k, _ in self.injector.scan_resources(
                lambda _, v: v.check(self.Attributes.TARGET)
            )
        ]

        return await asyncio.gather(
            *[async_map(name, self.injector.require_async(name)) for name in root_names]
        )

    async def targets(
        self,
        parent: Optional[tuple[str, Recipe]] = None,
        visited: Optional[set[Recipe]] = None,
    ) -> list[tuple[str, Recipe]]:
        results = []
        visited = visited or set()
        if parent is None:
            for name, recipe in await self.root_targets():
                results.append((name, recipe))
                if recipe.target:
                    results.append((str(recipe.target), recipe))
                visited.add(recipe)
                results.extend(await self.targets((name, recipe), visited))
        else:
            parent_name, parent_recipe = parent
            for recipe in parent_recipe.components():
                joined_name = self.TARGET_SEP.join(
                    [parent_name, str(recipe.target_or(recipe.name))]
                )
                if recipe not in visited:
                    results.append((joined_name, recipe))
                    visited.add(recipe)
                results.extend(await self.targets((joined_name, recipe), visited))
        return results

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

    def recipe(self, *args, **kwargs):
        return base_recipe(*args, **kwargs)

    def target(
        self,
        name_or_f: Optional[str | Callable] = None,
        *,
        default=False,
        factory=True,
        fail_f: Optional[FormatF] = None,
        keep=False,
        memoize=True,
        ok_f: Optional[FormatF] = None,
        start_f: Optional[FormatF] = None,
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

        See `xeno.cookbook.recipe` for info about the other params, note that
        `factory` and `memoize` params to `xeno.cookbook.recipe()` are always
        `True` here.
        """

        name = None if callable(name_or_f) else name_or_f

        def wrapper(f):
            target_wrapper = cast(
                Recipe,
                base_recipe(
                    name, factory=factory, keep=keep, sync=sync, memoize=memoize
                )(f),
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

    async def _resolve_targets(self, config: Config) -> list[tuple[str, Recipe]]:
        target_names = config.targets
        if not target_names:
            default_target = self.default_target()
            if default_target is not None:
                target_names = [default_target]
            else:
                raise ValueError("No target specified and no default target defined.")

        targets = await asyncio.gather(
            *[
                async_map(name, self.injector.require_async(name))
                for name in target_names
            ]
        )

        for name, target in targets:
            assert isinstance(
                target, Recipe
            ), f"Target `{name}` did not yield a recipe."

        return targets

    async def _make_targets(self, config, targets):
        scan = Recipe.Scanner()
        scan.scan_params(*[v for _, v in targets])
        while scan.has_recipes():
            await scan.gather_all()

        return scan.args(Recipe.PassMode.RESULTS)

    async def _clean_targets(self, config, targets):
        match config.cleanup_mode:
            case Config.CleanupMode.SHALLOW:
                return await asyncio.gather(*[t.clean() for _, t in targets])
            case Config.CleanupMode.RECURSIVE:
                return await asyncio.gather(
                    *[t.clean() for _, t in targets],
                    *[t.clean_components() for _, t in targets],
                )
            case _:
                raise ValueError("Config.cleanup_mode not specified.")

    async def _list_targets(self):
        targets = sorted(await self.root_targets())
        for name, _ in targets:
            print(name)
        return targets

    async def _list_target_tree(self):
        targets = sorted(await self.targets())
        for name, _ in targets:
            print(name)
        return targets

    async def build_async(self, *argv) -> list[Any]:
        bus = EventBus.get()

        try:
            config = Config("Xeno Build Engine v5").parse_args(*argv)
            targets = await self._resolve_targets(config)

            match config.mode:
                case Config.Mode.BUILD:
                    return await self._make_targets(config, targets)
                case Config.Mode.CLEAN:
                    return await self._clean_targets(config, targets)
                case Config.Mode.LIST:
                    return await self._list_targets()
                case Config.Mode.REBUILD:
                    await self._clean_targets(config, targets)
                    return await self._make_targets(config, targets)
                case Config.Mode.TREE:
                    return await self._list_target_tree()
                case _:
                    raise RuntimeError("Unknown mode encountered.")

        finally:
            bus.shutdown()

    async def _build_loop(self, bus, *argv):
        result, _ = await asyncio.gather(self.build_async(*argv), bus.run())
        return result

    def build(self, *argv):
        with EventBus.session():
            bus = EventBus.get()
            for hook in self.bus_hooks:
                hook(bus)
            return asyncio.run(self._build_loop(bus, *argv))


# --------------------------------------------------------------------
class DefaultEngineHook:
    def sigil(self, event, **kwargs):
        bkt = partial(color, fg='white', render='bold')
        sb = io.StringIO()
        sb.write(bkt('['))
        sb.write(color(event.context.sigil(event.context), **kwargs))
        sb.write(bkt(']'))
        sb.write(' ')
        return sb.getvalue()

    def on_clean(self, event):
        clr = partial(color, fg='white')
        sb = io.StringIO()
        sb.write(self.sigil(event, fg='green', render='bold'))
        sb.write(clr(event.context.clean_f(event.context)))
        print(sb.getvalue())

    def on_error(self, event):
        clr = partial(color, fg='red')
        sb = io.StringIO()
        sb.write(self.sigil(event, fg='red', render='bold'))
        sb.write(clr(event.data))
        print(sb.getvalue())

    def on_fail(self, event):
        clr = partial(color, fg='white')
        sb = io.StringIO()
        sb.write(self.sigil(event, fg='red', render='bold'))
        sb.write(clr(event.context.fail_f(event.context)))
        print(sb.getvalue())

    def on_info(self, event: Event):
        clr = partial(color, fg='white', render='dim')
        sb = io.StringIO()
        sb.write(self.sigil(event, fg='white', render='dim'))
        sb.write(clr(event.data))
        print(sb.getvalue())

    def on_start(self, event: Event):
        clr = partial(color, fg='white')
        sb = io.StringIO()
        sb.write(self.sigil(event, fg='cyan', render='bold'))
        sb.write(clr(event.context.start_f(event.context)))
        print(sb.getvalue())

    def on_success(self, event: Event):
        clr = partial(color, fg='white')
        sb = io.StringIO()
        sb.write(self.sigil(event, fg='green', render='bold'))
        sb.write(clr(event.context.ok_f(event.context)))
        print(sb.getvalue())

    def on_warning(self, event: Event):
        clr = partial(color, fg='white')
        sb = io.StringIO()
        sb.write(self.sigil(event, fg='yellow', render='bold'))
        sb.write(clr(event.data))
        print(sb.getvalue())

    def __call__(self, bus: EventBus):
        bus.subscribe(Events.CLEAN, self.on_clean)
        bus.subscribe(Events.ERROR, self.on_error)
        bus.subscribe(Events.FAIL, self.on_fail)
        bus.subscribe(Events.INFO, self.on_info)
        bus.subscribe(Events.START, self.on_start)
        bus.subscribe(Events.SUCCESS, self.on_success)
        bus.subscribe(Events.WARNING, self.on_warning)

# --------------------------------------------------------------------
engine = Engine()
engine.add_hook(DefaultEngineHook())
provide = engine.provide
recipe = engine.recipe
target = engine.target
build = engine.build
