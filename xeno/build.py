# --------------------------------------------------------------------
# build.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Friday March 17, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
import multiprocessing
import sys
from argparse import ArgumentParser, HelpFormatter
from collections import defaultdict
from typing import Any, Callable, Iterable, Optional, cast

from xeno.async_injector import AsyncInjector
from xeno.attributes import MethodAttributes
from xeno.color import TextDecorator
from xeno.color import disable as disable_color
from xeno.color import enable as enable_color
from xeno.cookbook import recipe as base_recipe
from xeno.decorators import named
from xeno.events import Event, EventBus
from xeno.recipe import BuildError, Events, Recipe
from xeno.shell import Environment, Shell
from xeno.spinner import Spinner

# --------------------------------------------------------------------
EngineHook = Callable[["Config", "Engine", EventBus], None]


# --------------------------------------------------------------------
class Config:
    class Mode:
        BUILD = "build"
        CLEAN = "clean"
        HELP = "help"
        LIST = "list"
        LIST_ALL = "list_all"
        REBUILD = "rebuild"
        TREE = "tree"

    class CleanupMode:
        NONE = "none"
        SHALLOW = "shallow"
        RECURSIVE = "recursive"

    class ColorOptions:
        YES = 'yes'
        NO = 'no'
        AUTO = 'auto'

    class SortingHelpFormatter(HelpFormatter):
        def add_arguments(self, actions):
            actions = sorted(actions, key=lambda a: a.option_strings)
            super().add_arguments(actions)

    def __init__(self):
        self.cleanup_mode = self.CleanupMode.NONE
        self.debug = False
        self.color = "auto"
        self.jobs = multiprocessing.cpu_count()
        self.mode = self.Mode.BUILD
        self.targets: list[str] = []
        self.tasks: list[str] = []
        self.verbose = 0

    def _argparser(self):
        parser = ArgumentParser(
            add_help=False,
            formatter_class=Config.SortingHelpFormatter,
        )
        parser.add_argument(
            "targets",
            nargs="*",
            help="Top-level task targets or addressable recipes to build.",
        )
        parser.add_argument(
            "--help",
            "-h",
            dest="mode",
            action="store_const",
            const=self.Mode.HELP,
            help="Show this help text.",
        )
        parser.add_argument(
            "--clean",
            "-c",
            dest="cleanup_mode",
            action="store_const",
            const=self.CleanupMode.RECURSIVE,
            help="Clean the specified or default targets and their components.",
        )
        parser.add_argument(
            "--cut",
            "-x",
            dest="cleanup_mode",
            action="store_const",
            const=self.CleanupMode.SHALLOW,
            help="Clean the specified or default targets only.",
        )
        parser.add_argument(
            "--rebuild",
            "-R",
            dest="mode",
            action="store_const",
            const=self.Mode.REBUILD,
            help="Clean and then rebuild the specified or default targets and their components.",
        )
        parser.add_argument(
            "--verbose",
            "-v",
            action="count",
            help="Print additional diagnostic or help info.",
        )
        parser.add_argument(
            "--list",
            "-l",
            dest="mode",
            action="store_const",
            const=self.Mode.LIST,
            help="List all top-level tasks targets.",
        )
        parser.add_argument(
            "--list-all",
            "-L",
            dest="mode",
            action="store_const",
            const=self.Mode.LIST_ALL,
            help="List all top-level task targets and their addressable components.",
        )
        parser.add_argument(
            "--tree",
            "-T",
            dest="mode",
            action="store_const",
            const=self.Mode.TREE,
            help="List all tasks and their components in a tree.",
        )
        parser.add_argument(
            "--debug",
            "-D",
            action="store_true",
            help="Enable debug and extra diagnostic info.",
        )
        parser.add_argument(
            "--color",
            choices=["yes", "no", "auto"],
            default="auto",
            help="Choose when to enable colorized output.",
        )
        parser.add_argument(
            "--jobs",
            "-j",
            dest="jobs",
            type=int,
            help="Number of simultaneous shells, defaults to number of CPUs.",
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
    TREE_SUB_ARROW = "⮡"

    class Attributes:
        TARGET = "xeno.build.task"
        DEFAULT = "xeno.build.default"

    def __init__(self, name="Build Script"):
        self.name = name
        self.bus_hooks: list[EngineHook] = list()
        self.env = Environment.context()
        self.injector = AsyncInjector()
        self.scan = Recipe.Scanner()
        self.txt = TextDecorator()

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
                    docs=f.__doc__,
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

        try:
            while self.scan.has_recipes():
                await self.scan.gather_all()

        except BuildError as e:
            self.txt.embrace("ERROR", fg="red", render="bold")
            self.txt(str(e))
            self.txt("FAIL", fg="red", render="bold")

        args = self.scan.args(Recipe.PassMode.RESULTS)
        self.scan.clear()
        self.txt("OK", fg="green", render="bold")
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

    async def _print_help(self, config: Config, tasks: Iterable[Recipe]):
        parser = config._argparser()

        self.txt(f"# {self.name}")
        self.txt(parser.format_help(), render="dim")
        self.txt("")
        self.txt("# Target Tasks")
        self._list_tasks(config, tasks)

    def _list_tasks(self, config: Config, tasks: Iterable[Recipe]):
        tasks = sorted(tasks, key=lambda t: t.callsign)
        for t in tasks:
            self.txt.write(t.callsign, fg="cyan")
            if t.docs:
                self.txt.write(f" {t.fmt.symbols.target} ")
                self.txt.write(t.docs, render="dim")
            self.txt("")
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

        first_indent = True
        for task in tasks:
            if indent > 0:
                self.txt.write("  " * indent)
                if first_indent:
                    self.txt.write(f" {self.TREE_SUB_ARROW} ", fg="white", render="dim")
                    first_indent = False
                else:
                    self.txt.write(f' {" " * len(self.TREE_SUB_ARROW)} ')

                self.txt.print(task.callsign)
            else:
                self.txt.print(task.callsign, fg="cyan", render="bold")

            if task not in visited:
                self._list_task_tree(task.children, indent + 1, new_visited)

        return 0

    async def build_async(self, config: Config) -> list[Any]:
        bus = EventBus.get()
        max_jobs = Shell.max_jobs

        try:
            Shell.set_max_jobs(config.jobs)
            tasks = await self._resolve_tasks(config)

            match config.mode:
                case Config.Mode.BUILD:
                    return await self._make_tasks(config, tasks)
                case Config.Mode.CLEAN:
                    return await self._clean_tasks(config, tasks)
                case Config.Mode.HELP:
                    return await self._print_help(config, await self.tasks())
                case Config.Mode.LIST:
                    return self._list_tasks(config, await self.tasks())
                case Config.Mode.LIST_ALL:
                    return self._list_tasks(
                        config, (await self.addressable_task_map()).values()
                    )

                case Config.Mode.REBUILD:
                    await self._clean_tasks(config, tasks)
                    return await self._make_tasks(config, tasks)
                case Config.Mode.TREE:
                    return self._list_task_tree(await self.tasks())
                case _:
                    raise RuntimeError("Unknown mode encountered.")

        finally:
            Shell.set_max_jobs(max_jobs)
            bus.shutdown()

    async def _build_loop(self, bus, config: Config):
        result, _ = await asyncio.gather(self.build_async(config), bus.run())
        return result

    def build(self, *argv, raise_errors=True):
        config = Config().parse_args(*argv)

        match config.color:
            case Config.ColorOptions.YES:
                enable_color()
            case Config.ColorOptions.NO:
                disable_color()
            case Config.ColorOptions.AUTO:
                pass

        try:
            with EventBus.session():
                bus = EventBus.get()
                for hook in self.bus_hooks:
                    hook(config, self, bus)
                return asyncio.run(self._build_loop(bus, config))

        except BuildError as e:
            if raise_errors:
                raise e


# --------------------------------------------------------------------
class DefaultEngineHook:
    def __init__(self):
        self.spinner = Spinner("resolving")
        self.txt: Optional[TextDecorator] = None

    def embrace(self, *content, **kwargs):
        assert self.txt
        return self.txt.embrace(*content, **kwargs)

    def print(self, *content, **kwargs):
        assert self.txt
        return self.txt(*content, **kwargs)

    def sigil(self, event):
        return event.context.sigil().replace(
            Recipe.SIGIL_DELIMITER, event.context.fmt.symbols.target
        )

    async def on_frame(self, event):
        assert self.txt
        self.spinner.message = f"resolving [{len(Recipe.active)}]"
        self.txt.wipe = await self.spinner.spin()

    def on_clean(self, event):
        self.embrace(self.sigil(event), fg="green", render="bold")
        self.print(event.context.fmt.clean(event.context))

    def on_error(self, event):
        self.embrace(self.sigil(event), fg="red", render="bold")
        self.print(event.data)

    def on_fail(self, event):
        self.embrace(self.sigil(event), fg="white", bg="red", render="bold")
        self.print(event.context.fmt.fail(event.context))

    def on_info(self, event: Event):
        self.embrace(self.sigil(event), fg="white", render="dim")
        self.print(event.data, fg="white", render="dim")

    def on_start(self, event: Event):
        self.embrace(self.sigil(event), fg="cyan", render="bold")
        self.print(event.context.fmt.start(event.context))

    def on_success(self, event: Event):
        self.embrace(self.sigil(event), fg="green", render="bold")
        self.print(event.context.fmt.ok(event.context))

    def on_warning(self, event: Event):
        self.embrace(self.sigil(event), fg="yellow", render="bold")
        self.print(event.data, fg="yellow", render="dim")

    def __call__(self, config: Config, engine: Engine, bus: EventBus):
        self.txt = engine.txt
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
