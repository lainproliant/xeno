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
import sys
from argparse import ArgumentParser
from collections import defaultdict
from functools import partial
from typing import Any, Callable, Iterable, Optional, cast

from xeno.async_injector import AsyncInjector
from xeno.attributes import MethodAttributes
from xeno.color import color
from xeno.cookbook import recipe as base_recipe
from xeno.decorators import named
from xeno.events import Event, EventBus
from xeno.recipe import BuildError, Events, Recipe
from xeno.shell import Environment
from xeno.spinner import Spinner

# --------------------------------------------------------------------
EngineHook = Callable[["Engine", EventBus], None]


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
        self.tasks: list[str] = []
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
    class Attributes:
        TARGET = "xeno.build.task"
        DEFAULT = "xeno.build.default"

    def __init__(self, name="Xeno v5 Build Engine"):
        self.name = name
        self.bus_hooks: list[EngineHook] = list()
        self.env = Environment.context()
        self.injector = AsyncInjector()
        self.scan = Recipe.Scanner()

    def add_hook(self, hook: EngineHook):
        self.bus_hooks.append(hook)

    async def tasks(self, *, parent: Optional[Recipe] = None) -> list[Recipe]:
        tasks = []
        if parent is None:
            root_names = [
                k
                for k, _ in self.injector.scan_resources(
                    lambda _, v: v.check(self.Attributes.TARGET)
                )
            ]

            for name in root_names:
                recipe = await self.injector.require_async(name)
                assert isinstance(
                    recipe, Recipe
                ), f"Task `{name}` did not yield a recipe."

                recipe.callsign = name
                tasks.append(recipe)
                await self.tasks(parent=recipe)

        else:
            for recipe in parent.components():
                recipe.parent = parent
                tasks.append(recipe)

        return tasks

    async def addressable_task_map(self) -> dict[str, Recipe]:
        all_tasks = [*Recipe.flat(await self.tasks())]
        callsign_counts: dict[str, int] = defaultdict(lambda: 0)
        for task in all_tasks:
            callsign_counts[task.callsign] += 1
        duplicate_callsigns = [k for k, v in callsign_counts.items() if v > 1]
        task_map = {t.callsign: t for t in all_tasks}
        for callsign in duplicate_callsigns:
            del task_map[callsign]
        return task_map

    def default_task(self) -> Optional[str]:
        results = [
            k
            for k, _ in self.injector.scan_resources(
                lambda _, v: v.check(self.Attributes.DEFAULT)
            )
        ]
        assert len(results) <= 1, "More than one default task specified."
        return results[0] if results else None

    def provide(self, *args, **kwargs):
        self.injector.provide(*args, **{**kwargs, "is_singleton": True})

    def recipe(self, *args, **kwargs):
        return base_recipe(*args, **kwargs)

    def task(
        self,
        name_or_f: Optional[str | Callable] = None,
        *,
        dep: Optional[str | Iterable[str]] = None,
        default=False,
        factory=True,
        fmt: Optional[Recipe.Format] = None,
        keep=False,
        memoize=True,
        sync=False,
    ):
        """
        Decorator for defining a task recipe for a build.

        Can be called with no parameters.  In this mode, the name is assumed
        to be the name of the decorated function and all other parameters
        are set to their defaults.

        If `default` is True, the task will be the default task
        when no task is specified at build time.  This method will
        throw ValueError if another task has already been specified
        as the default task.

        See `xeno.cookbook.recipe` for info about the other params, note that
        `factory` and `memoize` params to `xeno.cookbook.recipe()` are always
        `True` here.
        """

        name = None if callable(name_or_f) else name_or_f

        def wrapper(f):
            target_wrapper = cast(
                Recipe,
                base_recipe(
                    name,
                    dep=dep,
                    factory=factory,
                    keep=keep,
                    sync=sync,
                    memoize=memoize,
                )(f),
            )
            attrs = MethodAttributes.for_method(target_wrapper, True, True)
            assert attrs is not None, "MethodAttributes were not written successfully."
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

    async def _resolve_tasks(self, config: Config) -> list[Recipe]:
        task_map = await self.addressable_task_map()
        task_names = config.targets

        if not task_names:
            default_task = self.default_task()
            if default_task is not None:
                task_names = [default_task]
            else:
                raise ValueError("No task specified and no default task defined.")

        tasks = [task_map[k] for k in task_names]

        return tasks

    async def _make_tasks(self, config, tasks):
        self.scan.scan_params(*tasks)
        while self.scan.has_recipes():
            await self.scan.gather_all()

        args = self.scan.args(Recipe.PassMode.RESULTS)
        self.scan.clear()
        return args

    async def _clean_tasks(self, config, tasks):
        match config.cleanup_mode:
            case Config.CleanupMode.SHALLOW:
                return await asyncio.gather(*[task.clean() for task in tasks])
            case Config.CleanupMode.RECURSIVE:
                return await asyncio.gather(
                    *[task.clean() for task in tasks],
                    *[task.clean_components(recursive=True) for task in tasks],
                )
            case _:
                raise ValueError("Config.cleanup_mode not specified.")

    def _list_tasks(self, tasks: Iterable[Recipe]):
        tasks = sorted(tasks, key=lambda t: t.name)
        for task in tasks:
            print(task.name)
        return tasks

    def _list_task_tree(
        self,
        tasks: Iterable[Recipe],
        indent=0,
        visited: Optional[set[Recipe]] = None,
    ):
        visited = visited or set()
        tasks = sorted((t for t in tasks if t not in visited), key=lambda t: t.callsign)
        new_visited = visited | set(tasks)

        for task in tasks:
            if indent > 0:
                print(f"{'  ' * indent} ⮡ {task.callsign}")
            else:
                print(f"{task.callsign}")

            if task not in visited:
                self._list_task_tree(task.children, indent + 1, new_visited)

        return 0

    async def build_async(self, *argv) -> list[Any]:
        bus = EventBus.get()

        try:
            config = Config("Xeno Build Engine v5").parse_args(*argv)
            tasks = await self._resolve_tasks(config)

            match config.mode:
                case Config.Mode.BUILD:
                    return await self._make_tasks(config, tasks)
                case Config.Mode.CLEAN:
                    return await self._clean_tasks(config, tasks)
                case Config.Mode.LIST:
                    return self._list_tasks(await self.tasks())
                case Config.Mode.REBUILD:
                    await self._clean_tasks(config, tasks)
                    return await self._make_tasks(config, tasks)
                case Config.Mode.TREE:
                    return self._list_task_tree(await self.tasks())
                case _:
                    raise RuntimeError("Unknown mode encountered.")

        finally:
            bus.shutdown()

    async def _build_loop(self, bus, *argv):
        result, _ = await asyncio.gather(self.build_async(*argv), bus.run())
        return result

    def build(self, *argv, raise_errors=True):
        try:
            with EventBus.session():
                bus = EventBus.get()
                for hook in self.bus_hooks:
                    hook(self, bus)
                return asyncio.run(self._build_loop(bus, *argv))
            print("OK")

        except BuildError as e:
            print("FAIL")
            if raise_errors:
                raise e


# --------------------------------------------------------------------
class DefaultEngineHook:
    def __init__(self):
        self.spinner = Spinner("resolving")
        self._clear_chars = 0

    def print(self, s):
        sys.stdout.write("\r")
        sys.stdout.write(" " * self._clear_chars)
        sys.stdout.write("\r")
        return print(s)

    def sigil(self, event, **kwargs):
        bkt = partial(color, fg="white", render="bold")
        sb = io.StringIO()
        sb.write(bkt("["))
        sigil = event.context.sigil().replace(
            Recipe.SIGIL_DELIMITER, event.context.fmt.symbols.target
        )
        sb.write(color(sigil, **kwargs))
        sb.write(bkt("]"))
        sb.write(" ")
        return sb.getvalue()

    async def on_frame(self, event):
        self.spinner.message = f"resolving [{len(Recipe.active)}]"
        self._clear_chars = await self.spinner.spin()

    def on_clean(self, event):
        clr = partial(color, fg="white")
        sb = io.StringIO()
        sb.write(self.sigil(event, fg="green", render="bold"))
        sb.write(clr(event.context.fmt.clean(event.context)))
        self.print(sb.getvalue())

    def on_error(self, event):
        clr = partial(color, fg="red")
        sb = io.StringIO()
        sb.write(self.sigil(event, fg="red", render="bold"))
        sb.write(clr(event.data))
        self.print(sb.getvalue())

    def on_fail(self, event):
        clr = partial(color, fg="white")
        sb = io.StringIO()
        sb.write(self.sigil(event, fg="red", render="bold"))
        sb.write(clr(event.context.fmt.fail(event.context)))
        self.print(sb.getvalue())

    def on_info(self, event: Event):
        clr = partial(color, fg="white", render="dim")
        sb = io.StringIO()
        sb.write(self.sigil(event, fg="white", render="dim"))
        sb.write(clr(event.data))
        self.print(sb.getvalue())

    def on_start(self, event: Event):
        clr = partial(color, fg="white")
        sb = io.StringIO()
        sb.write(self.sigil(event, fg="cyan", render="bold"))
        sb.write(clr(event.context.fmt.start(event.context)))
        self.print(sb.getvalue())

    def on_success(self, event: Event):
        clr = partial(color, fg="white")
        sb = io.StringIO()
        sb.write(self.sigil(event, fg="green", render="bold"))
        sb.write(clr(event.context.fmt.ok(event.context)))
        self.print(sb.getvalue())

    def on_warning(self, event: Event):
        clr = partial(color, fg="white")
        sb = io.StringIO()
        sb.write(self.sigil(event, fg="yellow", render="bold"))
        sb.write(clr(event.data))
        self.print(sb.getvalue())

    def __call__(self, engine: Engine, bus: EventBus):
        bus.subscribe(Events.CLEAN, self.on_clean)
        bus.subscribe(Events.ERROR, self.on_error)
        bus.subscribe(Events.FAIL, self.on_fail)
        bus.subscribe(Events.INFO, self.on_info)
        bus.subscribe(Events.START, self.on_start)
        bus.subscribe(Events.SUCCESS, self.on_success)
        bus.subscribe(Events.WARNING, self.on_warning)
        bus.subscribe(EventBus.FRAME, self.on_frame)


# --------------------------------------------------------------------
engine = Engine()
engine.add_hook(DefaultEngineHook())
provide = engine.provide
recipe = engine.recipe
task = engine.task


# --------------------------------------------------------------------
def build():
    return engine.build(*sys.argv[1:], raise_errors=False)
