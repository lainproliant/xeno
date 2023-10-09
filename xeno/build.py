# --------------------------------------------------------------------
# build.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Friday March 17, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
import fnmatch
import multiprocessing
import sys
import traceback
from argparse import ArgumentParser, HelpFormatter, REMAINDER
from collections import defaultdict
from typing import Any, Callable, Iterable, Optional, cast
from datetime import datetime, timedelta

from xeno.async_injector import AsyncInjector
from xeno.attributes import MethodAttributes
from xeno.color import TextDecorator
from xeno.color import disable as disable_color
from xeno.color import enable as enable_color
from xeno.color import is_enabled as is_color_enabled
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
        QUERY = "query"

    class CleanupMode:
        NONE = "none"
        SHALLOW = "shallow"
        RECURSIVE = "recursive"
        RECURSIVE_WITH_DEPS = "recursive_with_deps"

    class ColorOptions:
        YES = "yes"
        NO = "no"
        AUTO = "auto"

    class SortingHelpFormatter(HelpFormatter):
        def add_arguments(self, actions):
            actions = sorted(actions, key=lambda a: a.option_strings)
            super().add_arguments(actions)

    def __init__(self):
        self.cleanup_mode = self.CleanupMode.NONE
        self.color = "auto"
        self.debug = False
        self.jobs = multiprocessing.cpu_count()
        self.mode = self.Mode.BUILD
        self.quiet = False
        self.targets: list[str] = []
        self.tasks: list[str] = []
        self.to_stdout = False
        self.verbose = 0
        self.query: Optional[str] = None

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
            help="Clean the specified or default targets and all their components.",
        )
        parser.add_argument(
            "--full-clean",
            "-C",
            dest="cleanup_mode",
            action="store_const",
            const=self.CleanupMode.RECURSIVE_WITH_DEPS,
            help="Clean the specified or default targets and all their components and dependencies.",
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
            "--quiet",
            "-q",
            action="store_true",
            help="Only print info/warning/error event contents to stderr, nothing else.",
        )
        parser.add_argument(
            "--query",
            "-Q",
            help="Return 0 if the given target or comma separated list of targets exist, 1 otherwise, do nothing else.",
        )
        parser.add_argument(
            "--to-stdout",
            "-s",
            action="store_true",
            help="Print info event contents to stdout, all else to stderr.",
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
        if self.query is not None:
            self.mode = Config.Mode.QUERY
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

        self._build_mode_methods = {
            Config.Mode.BUILD: self._build_mode_build,
            Config.Mode.CLEAN: self._build_mode_clean,
            Config.Mode.HELP: self._build_mode_help,
            Config.Mode.LIST: self._build_mode_list,
            Config.Mode.QUERY: self._build_mode_query,
            Config.Mode.LIST_ALL: self._build_mode_list_all,
            Config.Mode.REBUILD: self._build_mode_rebuild,
            Config.Mode.TREE: self._build_mode_tree,
        }

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

    def factory(self, *args, **kwargs):
        return base_recipe(*args, **kwargs, factory=True)

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
        cleanup: Optional[str | Iterable[str]] = None,
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
                    cleanup=cleanup,
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
        task_map: dict[str, Recipe] = await self.addressable_task_map()
        targets = config.targets

        if not targets:
            default_task = self.default_task()
            if default_task is not None:
                targets = [default_task]
            else:
                raise ValueError("No task specified and no default task defined.")

        task_names: set[str] = set()
        tasks = []
        for target in targets:
            results = fnmatch.filter(task_map.keys(), target)
            if len(results) < 1:
                raise ValueError(f"Target filter `{target}` matched no defined targets.")

            for name in results:
                if name not in task_names:
                    task_names.add(name)
                    tasks.append(task_map[name])

        return tasks

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

            try:
                mode_method = self._build_mode_methods[config.mode]

            except IndexError:
                raise RuntimeError("Unknown build mode encountered: {config.mode}")

            return await mode_method(config)

        finally:
            Shell.set_max_jobs(max_jobs)
            bus.shutdown()

    async def _build_mode_build(self, config: Config):
        tasks = await self._resolve_tasks(config)
        self.scan.scan_params(*tasks)

        try:
            while self.scan.has_recipes():
                await self.scan.gather_all()

            args = self.scan.args(Recipe.PassMode.RESULTS)
            self.scan.clear()
            self.txt("OK", fg="green", render="bold")
            return args

        except BuildError as e:
            self.txt.embrace("ERROR", fg="red", render="bold")
            self.txt("FAIL", fg="red", render="bold")
            raise e

    async def _build_mode_clean(self, config: Config):
        tasks = await self._resolve_tasks(config)
        match config.cleanup_mode:
            case Config.CleanupMode.SHALLOW:
                return await asyncio.gather(*[task.clean() for task in tasks])
            case Config.CleanupMode.RECURSIVE:
                return await asyncio.gather(
                    *[task.clean() for task in tasks],
                    *[task.clean_components(recursive=True) for task in tasks],
                )
            case Config.CleanupMode.RECURSIVE_WITH_DEPS:
                return await asyncio.gather(
                    *[task.clean() for task in tasks],
                    *[task.clean_components(recursive=True) for task in tasks],
                )
            case _:
                raise ValueError("Config.cleanup_mode not specified.")

    async def _build_mode_help(self, config: Config):
        tasks = await self.tasks()
        parser = config._argparser()

        self.txt(f"# {self.name}")
        self.txt(parser.format_help(), render="dim")
        self.txt("")
        self.txt("# Target Tasks")
        self._list_tasks(config, tasks)

    async def _build_mode_list(self, config: Config):
        return self._list_tasks(config, await self.tasks())

    async def _build_mode_list_all(self, config: Config):
        return self._list_tasks(config, (await self.addressable_task_map()).values())

    async def _build_mode_query(self, config: Config):
        assert config.query is not None
        tasks = await self.tasks()
        task_names = set([t.callsign for t in tasks])
        query_names = config.query.split(",")
        missing_names = [name for name in query_names if name not in task_names]
        return len(missing_names)

    async def _build_mode_rebuild(self, config: Config):
        await self._build_mode_clean(config)
        return await self._build_mode_build(config)

    async def _build_mode_tree(self, config: Config):
        return self._list_task_tree(await self.tasks())

    async def _build_loop(self, bus, config: Config):
        result, _ = await asyncio.gather(self.build_async(config), bus.run())
        return result

    def build(self, *argv_, raise_errors=False):
        target_argv = [*argv_]
        build_argv = []

        while target_argv:
            arg = target_argv.pop(0)
            if arg == "@":
                break
            build_argv.append(arg)

        config = Config().parse_args(*build_argv)

        @self.provide
        def argv():
            return target_argv

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
            if config.debug:
                traceback.print_exc()
            if raise_errors:
                raise e


# --------------------------------------------------------------------
class DefaultEngineHook:
    def __init__(self):
        self.spinner = Spinner("resolving")
        self.txt: Optional[TextDecorator] = None
        self.quiet = False
        self.to_stdout = False
        self.active_offset = -1
        self.active_inc_dt = datetime.min
        self.print_len = 0

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
        if self.quiet:
            return
        assert self.txt

        now = datetime.now()
        sorted_active = sorted(Recipe.active, key=lambda r: r.sigil())

        if now > self.active_inc_dt:
            self.active_offset += 1
            self.active_inc_dt = now + timedelta(seconds=1)

        if self.active_offset >= len(sorted_active):
            self.active_offset = 0

        if sorted_active:
            recipe = sorted_active[self.active_offset]
            message = f"resolving {len(Recipe.active)} [{recipe.sigil()}]"
        else:
            message = ""

        if message != self.spinner.message:
            self.txt.wipeline(self.print_len)
            self.spinner.message = message
        self.txt.wipe = self.print_len = await self.spinner.spin()

    def on_clean(self, event):
        if self.quiet:
            return
        self.embrace(self.sigil(event), fg="green", render="bold")
        self.print(event.context.fmt.clean(event.context))

    def on_error(self, event):
        if not self.quiet:
            self.embrace(self.sigil(event), fg="red", render="bold")
        self.print(event.data)

    def on_fail(self, event):
        if self.quiet:
            return
        self.embrace(self.sigil(event), fg="white", bg="red", render="bold")
        self.print(event.context.fmt.fail(event.context))

    def on_info(self, event: Event):
        if not self.quiet and not self.to_stdout:
            self.embrace(self.sigil(event), fg="white", render="dim")
        if self.to_stdout:
            print(event.data)
        else:
            self.print(event.data, fg="white", render="dim")

    def on_start(self, event: Event):
        if self.quiet:
            return
        self.embrace(self.sigil(event), fg="cyan", render="bold")
        self.print(event.context.fmt.start(event.context))

    def on_success(self, event: Event):
        if self.quiet:
            return
        self.embrace(self.sigil(event), fg="green", render="bold")
        self.print(event.context.fmt.ok(event.context))

    def on_warning(self, event: Event):
        if not self.quiet:
            self.embrace(self.sigil(event), fg="yellow", render="bold")
            self.print(event.data, fg="yellow", render="dim")
        else:
            self.print(event.data)

    def __call__(self, config: Config, engine: Engine, bus: EventBus):
        self.txt = engine.txt
        self.spinner.colorized = is_color_enabled()
        self.quiet = config.quiet
        self.to_stdout = config.to_stdout
        for event, listener in [
            (Events.CLEAN, self.on_clean),
            (Events.ERROR, self.on_error),
            (Events.FAIL, self.on_fail),
            (Events.INFO, self.on_info),
            (Events.START, self.on_start),
            (Events.SUCCESS, self.on_success),
            (Events.WARNING, self.on_warning),
            (EventBus.FRAME, self.on_frame),
        ]:
            bus.subscribe(event, listener)


# --------------------------------------------------------------------
engine = Engine()
engine.add_hook(DefaultEngineHook())
provide = engine.provide
recipe = engine.recipe
factory = engine.factory
task = engine.task


# --------------------------------------------------------------------
def build():
    result = engine.build(*sys.argv[1:])
    if isinstance(result, int):
        sys.exit(result)
    sys.exit(0)
