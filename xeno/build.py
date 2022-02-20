# --------------------------------------------------------------------
# build.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Sunday October 18, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
import atexit
import fnmatch
import itertools
import multiprocessing
import os
import shlex
import shutil
import sys
import traceback
from argparse import ArgumentParser
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import partial
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    Generic,
    Iterable,
    List,
    Optional,
    Set,
    TypeVar,
    Union,
)

from xeno import Injector, MethodAttributes
from xeno.color import clreol, color
from xeno.color import enable as enable_color
from xeno.color import hide_cursor, show_cursor, style
from xeno.shell import EnvDict, Shell
from xeno.utils import async_wrap, file_age, is_iterable

# --------------------------------------------------------------------
T = TypeVar("T")
TARGET_ATTR = "xeno.build.target"
DEFAULT_ATTR = "xeno.build.default"

# --------------------------------------------------------------------
_error = partial(color, fg="black", bg="red")
_info = partial(color, fg="white", render="dim")
_ok = partial(color, fg="green")
_start = partial(color, fg="cyan")
_warning = partial(color, fg="red", render="dim")
_debug = partial(color, fg="magenta", render="dim")

# --------------------------------------------------------------------
class Event(Enum):
    CLEAN = "clean"
    DEBUG = "debug"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    START = "start"
    SUCCESS = "success"


# --------------------------------------------------------------------
class Mode(Enum):
    BUILD = "build"
    REBUILD = "rebuild"
    SNIP = "snip"
    CLEAN = "clean"
    LIST_TARGETS = "list_targets"
    PRINT_TREE = "print_tree"


# --------------------------------------------------------------------
class CleanupMode(Enum):
    RECIPE = "recipe"
    SHALLOW = "shallow"
    RECURSIVE = "recursive"


# --------------------------------------------------------------------
@dataclass
class EventData:
    event: Event
    recipe: "Recipe"
    content: Any


# --------------------------------------------------------------------
EventWatcher = Callable[[EventData], None]

# --------------------------------------------------------------------
class Recipe:
    """A recipe represents a repeatable action which may be reversible."""

    @staticmethod
    def suss_one(param: Any) -> Optional["Recipe"]:
        if isinstance(param, Recipe):
            return param
        return None

    @staticmethod
    def suss(params: Dict[str, Any]) -> Generator["Recipe", None, None]:
        """Suss out any recipes from the given dictionary values."""
        for k, v in params.items():
            if is_iterable(v):
                for x in v:
                    sussed = Recipe.suss_one(v)
                    if isinstance(sussed, Recipe):
                        yield sussed
            else:
                sussed = Recipe.suss_one(v)
                if isinstance(sussed, Recipe):
                    yield sussed

    def __init__(
        self,
        input: Optional[Iterable["Recipe"]] = None,
        synchronous=False,
        *,
        setup: Optional["Recipe"] = None,
    ):
        self.name = self.__class__.__name__
        self.was_named = False
        self.setup = setup
        self.inputs = [r.with_setup(setup) for r in input or []]
        self.synchronous = synchronous
        self.watchers: List[EventWatcher] = []
        self.origin: Optional[str] = None
        self.lock = asyncio.Lock()
        self.failed = False
        self.hide = False

    def named(self, name: str) -> "Recipe":
        self.name = name
        self.was_named = True
        return self

    def with_prefix(self, prefix: str) -> "Recipe":
        parts = self.name.split(":")
        parts[-1] = prefix + parts[-1]
        return self.named(":".join(parts))

    def with_type(self, type_name: str) -> "Recipe":
        parts = self.name.split(":")
        if len(parts) > 1:
            parts[0] = type_name
        else:
            parts.insert(0, type_name)
        return self.named(":".join(parts))

    def with_setup(self, setup: Optional["Recipe"]) -> "Recipe":
        if setup is None:
            return self
        if self.setup is not None:
            self.setup.inputs.append(setup)
        else:
            self.setup = setup
        return self

    def reveal(self, recipe: "Recipe") -> "Recipe":
        """Reveal an internal Recipe by exposing it to this recipe's watchers."""
        recipe.watchers.extend(self.watchers)
        for input in recipe.inputs:
            self.reveal(input)
        if recipe.setup is not None:
            self.reveal(recipe.setup)
        return recipe

    def watch(self, watcher: EventWatcher):
        if watcher not in self.watchers:
            self.watchers.append(watcher)
        for input in self.inputs:
            input.watch(watcher)
        if self.setup is not None:
            self.setup.watch(watcher)

    def trigger(self, event: Event, content: Any = None) -> EventData:
        event_data = EventData(event, self, content)
        for watcher in self.watchers:
            watcher(event_data)
        return event_data

    async def resolve(self):
        self.failed = False
        async with self.lock:
            if self.done and not self.outdated:
                return
            try:
                assert self.ready, "Recipe %s isn't ready." % self.name
                if self.setup is not None:
                    await self.setup.resolve()
                if self.synchronous:
                    for recipe in self.inputs:
                        await recipe.resolve()
                else:
                    await asyncio.gather(*(recipe.resolve() for recipe in self.inputs))

                total_incomplete = 0
                for recipe in self.inputs:
                    if not recipe.done:
                        total_incomplete += 1
                        self.trigger(
                            Event.ERROR,
                            f"Recipe '{recipe.name}' didn't complete successfully.",
                        )

                assert (
                    total_incomplete == 0
                ), f"{total_incomplete} recipe{'' if total_incomplete == 1 else 's'} didn't complete successfully."
                assert all(
                    recipe.done and not recipe.outdated for recipe in self.inputs
                ), "Some recipes didn't complete successfully."
                await self.make()
                assert self.done, "Recipe '%s' isn't done after make." % self.name
                if self.outdated:
                    self.trigger(
                        Event.WARNING,
                        "Recipe '%s' is out of date after make." % self.name,
                    )
                self.trigger(Event.SUCCESS)

            except Exception as e:
                self.failed = True
                self.trigger(Event.ERROR, e)

    async def spin(self, interval: float = 0.05, delay: float = 0.25):
        if not sys.stdout.isatty():
            return

        spinner_shape = [
            "[=   ]",
            "[==  ]",
            "[=== ]",
            "[====]",
            "[ ===]",
            "[  ==]",
            "[   =]",
            "[    ]",
        ]
        ansi_spinner_shape = []

        for shape in spinner_shape:
            ansi_spinner_shape.append(
                "".join(
                    [shape[0], color(shape[1:-1], fg="red", render="dim"), shape[-1]]
                )
            )

        spinner = itertools.cycle(ansi_spinner_shape)
        start = datetime.now()

        try:
            hide_cursor()
            atexit.register(show_cursor)
            while not (self.done or self.failed):
                if datetime.now() - start > timedelta(seconds=delay):
                    sys.stdout.write(next(spinner) + color(" resolving", render="dim"))
                    sys.stdout.write("\r")
                    sys.stdout.flush()
                await asyncio.sleep(interval)
        finally:
            atexit.unregister(show_cursor)
            show_cursor()

    async def make(self):
        """Generate the final recipe result once all inputs are done."""
        pass

    async def clean(self):
        """Clean the final recipe result."""
        for recipe in self.inputs:
            await recipe.cleanup(CleanupMode.RECIPE)

    async def cleanup(self, mode: CleanupMode = CleanupMode.RECURSIVE):
        """Cleanup the final result and all input results."""
        async with self.lock:
            if mode == CleanupMode.SHALLOW:
                await self.clean()
                for recipe in self.inputs:
                    await recipe.cleanup(CleanupMode.RECIPE)

            elif mode == CleanupMode.RECURSIVE:
                await self.clean()
                for recipe in self.inputs:
                    await recipe.cleanup(CleanupMode.RECURSIVE)

            elif mode == CleanupMode.RECIPE:
                await self.clean()

            else:
                raise ValueError("Invalid cleanup mode specified.")

    @property
    def result(self):
        """The result of the recipe.  Defaults to the result of all inputs."""
        return [recipe.result for recipe in self.inputs]

    @property
    def ready(self):
        """Determine if prerequisites are met for this recipe."""
        return True

    @property
    def min_input_age(self):
        return min(r.age for r in self.inputs) if self.inputs else timedelta.max

    @property
    def inputs_outdated(self):
        return any(r.outdated for r in self.inputs)

    @property
    def outdated(self):
        return self.inputs_outdated

    @property
    def done(self):
        """Whether the full result of this recipe exists."""
        return all(recipe.done for recipe in self.inputs)

    @property
    def age(self) -> timedelta:
        if not self.inputs:
            raise NotImplementedError()
        return min(r.age for r in self.inputs)

    def tokenize(self) -> List[str]:
        """Generate a list of tokens from the value for command interpolation."""
        tokens: List[str] = []
        if is_iterable(self.result):
            tokens.extend(str(item) for item in self.result)
        else:
            tokens.append(str(self.result))
        return tokens

    def __str__(self):
        return " ".join(shlex.quote(s) for s in self.tokenize())

    def __iter__(self):
        return iter(self.inputs)


# --------------------------------------------------------------------
class ValueRecipe(Recipe, Generic[T]):
    def __init__(self, input: Optional[Iterable["Recipe"]] = None):
        super().__init__(input)
        self._result: Optional[T] = None
        self.hide = True

    async def make(self):
        self._result = await self.compute()

    async def compute(self) -> T:
        raise NotImplementedError()

    @property
    def result(self) -> T:
        assert self._result is not None, "Result wasn't computed for '%s'." % self.name
        return self._result

    def tokenize(self) -> List[str]:
        if self._result is None:
            return []
        else:
            return super().tokenize()

    @property
    def done(self) -> bool:
        return self._result is not None


# --------------------------------------------------------------------
class FileRecipe(Recipe):
    def __init__(
        self,
        output: Union[str, Path],
        input: Optional[Iterable[Recipe]] = None,
        requires: Optional[Iterable[Path]] = None,
    ):
        super().__init__(input)
        self.named(Path(output).name)
        self.output = Path(output)
        self.requires = list(requires or [])

    async def resolve(self):
        for path in self.requires:
            assert path.exists(), "Required path %s does not exist." % path
        await super().resolve()

    @property
    def ready(self):
        return all(path.exists() for path in self.requires)

    def _is_done(self):
        return self.output.exists()

    @property
    def done(self):
        """Whether the full result of this recipe exists."""
        return self._is_done()

    @property
    def age(self) -> timedelta:
        if not self.output.exists():
            return timedelta.max
        return datetime.now() - datetime.fromtimestamp(self.output.stat().st_mtime)

    @property
    def min_require_age(self) -> timedelta:
        return (
            min(file_age(f) for f in self.requires) if self.requires else timedelta.max
        )

    @property
    def outdated(self) -> bool:
        return (
            self.inputs_outdated
            or self.age > self.min_input_age
            or self.age > self.min_require_age
        )

    @property
    def result(self) -> Path:
        return self.output

    async def clean(self):
        if not self.output.exists():
            return

        self.trigger(Event.CLEAN, "delete %s" % str(self.output))
        if self.output.is_dir():
            shutil.rmtree(self.output)
        else:
            self.output.unlink()

    async def make(self):
        """Abstract method: generate the file once all inputs are done."""
        raise NotImplementedError()


# --------------------------------------------------------------------
class StaticFileRecipe(FileRecipe):
    def __init__(self, static_file: Union[str, Path]):
        super().__init__(Path(static_file))
        self.named(Path(static_file).name)
        self.output = Path(static_file)
        self.hide = True

    async def resolve(self):
        assert self.output.exists(), "Static file does not exist: %s" % self.output

    async def clean(self):
        pass

    @property
    def outdated(self):
        return False


# --------------------------------------------------------------------
class ShellRecipeMixin(Recipe):
    shell: Shell
    cmd: Union[str, Iterable[str]]
    params: EnvDict
    redacted: Set[str]
    require_success: bool
    interactive: bool
    returncode: Optional[int]

    def log_stdout(self, line: str, stdin: asyncio.StreamWriter):
        self.trigger(Event.INFO, line)

    def log_stderr(self, line: str, stdin: asyncio.StreamWriter):
        self.trigger(Event.WARNING, line)

    def shell_mixin_init(
        self,
        cmd: Union[str, Iterable[str]],
        env: Optional[EnvDict],
        cwd: Optional[Union[Path, str]] = None,
        redacted: Optional[Iterable[str]] = None,
        require_success=True,
        interactive=False,
        **params,
    ):
        self.shell = Shell(
            {**os.environ, **(env or {})}, Path(cwd) if cwd is not None else Path.cwd()
        )
        self.cmd = cmd
        self.params = params
        self.redacted = set(redacted or [])
        self.require_success = require_success
        self.interactive = interactive
        self.returncode = None

    async def make(self):
        self.trigger(
            Event.START,
            self.shell.interpolate(
                self.cmd,
                self._merge_params(),
                {
                    "*": partial(
                        color, fg="blue", render="dim", after=style(render="dim")
                    ),
                    "output": partial(color, fg="green", after=style(render="dim")),
                },
                self.redacted,
            ),
        )

        if self.interactive:
            self.returncode = self.shell.interact(self.cmd, **self._merge_params())

        else:
            self.returncode = await self.shell.run(
                self.cmd,
                stdout=self.log_stdout,
                stderr=self.log_stderr,
                **self._merge_params(),
            )

        assert self.returncode == 0 or not self.require_success, "Command failed."

    def _merge_params(self) -> EnvDict:
        return self.params

    def _is_done(self):
        return (
            self.returncode == 0
            if self.require_success
            else self.returncode is not None
        )


# --------------------------------------------------------------------
class ShellRecipe(ShellRecipeMixin):
    def __init__(
        self,
        cmd: Union[str, Iterable[str]],
        env: Optional[EnvDict] = None,
        redacted: Optional[Iterable[str]] = None,
        require_success=True,
        interactive=False,
        cwd: Optional[Union[Path, str]] = None,
        **params,
    ):
        super().__init__(Recipe.suss(params))
        if isinstance(cmd, str):
            self.named(shlex.split(cmd)[0])
        else:
            cmd = [*cmd]
            self.named(cmd[0])

        self.shell_mixin_init(
            cmd, env, cwd, redacted, require_success, interactive, **params
        )
        self.name = Path(
            shlex.split(self.shell.interpolate(cmd, self._merge_params()))[0]
        ).stem

    @property
    def done(self):
        return self._is_done()


# --------------------------------------------------------------------
class ShellFileRecipe(ShellRecipeMixin, FileRecipe):
    def __init__(
        self,
        cmd: Union[str, Iterable[str]],
        output: Union[str, Path],
        env: Optional[EnvDict] = None,
        redacted: Optional[Iterable[str]] = None,
        requires: Optional[Iterable[Path]] = None,
        require_success=True,
        interactive=False,
        cwd: Optional[Union[Path, str]] = None,
        **params,
    ):
        FileRecipe.__init__(self, output, Recipe.suss(params), requires)
        self.shell_mixin_init(
            cmd, env, cwd, redacted, require_success, interactive, **params
        )

    def _merge_params(self) -> EnvDict:
        return {
            **self.params,
            "output": self.output,
            "requirements": self.requires,
        }

    @property
    def done(self):
        return FileRecipe._is_done(self)


# --------------------------------------------------------------------
def sh(*args, **kwargs) -> Recipe:
    if "output" in kwargs:
        return ShellFileRecipe(*args, **kwargs)
    return ShellRecipe(*args, **kwargs)


# --------------------------------------------------------------------
class BuildEngine:
    def __init__(self):
        self._injector: Optional[Injector] = None

    @property
    def injector(self) -> Injector:
        if self._injector is None:
            self._injector = Injector()
        return self._injector

    @property
    def targets(self) -> List[str]:
        return [
            k
            for k, v in self.injector.scan_resources(lambda k, v: v.check(TARGET_ATTR))
        ]

    @property
    def default_target(self) -> Optional[str]:
        results = [
            k
            for k, v in self.injector.scan_resources(lambda k, v: v.check(DEFAULT_ATTR))
        ]
        assert len(results) <= 1, "More than one default target specified."
        return results[0] if results else None

    def provide(self, f):
        self.injector.provide(f, is_singleton=True)

    def target(self, f):
        @MethodAttributes.wraps(f)
        async def wrapper(*args, **kwargs):
            result = await async_wrap(f, *args, **kwargs)
            assert result is not None, (
                "Target definition for '%s' didn't return a value." % f.__name__
            )
            if is_iterable(result):
                results = list(result)
                assert all(
                    isinstance(obj, Recipe) for obj in results
                ), "Target definition for '%s' returned an iterable containing non-Recipe values (e.g. '%s')." % (
                    f.__name__,
                    next(
                        type(obj).__qualname__
                        for obj in result
                        if not isinstance(obj, Recipe)
                    ),
                )
                result = Recipe(results, synchronous=isinstance(result, tuple))
            if isinstance(result, Recipe) and not result.was_named:
                result = result.named(f.__name__)
            assert isinstance(
                result, Recipe
            ), "Target definition for '%s' returned a non-Recipe value ('%s')." % (
                f.__name__,
                type(result).__qualname__,
            )
            result.origin = f.__name__
            return result

        attrs = MethodAttributes.for_method(wrapper, True, True)
        attrs.put(TARGET_ATTR)
        self.provide(wrapper)
        return wrapper

    def default(self, f):
        wrapper = self.target(f)
        attrs = MethodAttributes.for_method(wrapper, True, True)
        attrs.put(DEFAULT_ATTR)
        return wrapper

    def _map_dependencies(self, recipe: Recipe) -> Dict[str, Recipe]:
        if recipe.hide:
            return {}
        deps = {recipe.name: recipe}
        for input in recipe.inputs:
            deps.update(self._map_dependencies(input))
        return deps

    def load_recipe(self, name: str) -> Recipe:
        recipe = self.injector.require(name)
        assert isinstance(recipe, Recipe), "The resource named '%s' isn't a Recipe."
        return recipe

    def load_targetable_recipe_map(self):
        recipe_map: Dict[str, Recipe] = {}
        for name in self.targets:
            recipe = self.load_recipe(name)
            recipe_map.update(self._map_dependencies(recipe))
        return recipe_map

    def _load_targets(self, targets: List[str]) -> Generator[Recipe, None, None]:
        recipe_map = self.load_targetable_recipe_map()

        for target in targets:
            if self.injector.has(target):
                yield self.load_recipe(target)

            elif matching := fnmatch.filter(recipe_map.keys(), target):
                for match in matching:
                    yield recipe_map[match]

            else:
                raise ValueError('Target isn\'t defined: "%s"' % target)

    def create(self, targets: Optional[Iterable[str]] = None):
        targets = list(targets if targets is not None else [])
        if not targets and self.default_target is not None:
            targets = [self.default_target]
        assert targets, "No targets were provided."
        recipes = list(self._load_targets(targets))
        assert all(
            isinstance(obj, Recipe) for obj in recipes
        ), "One or more target definitions returned a non-Recipe value."
        return Recipe(recipes).named("build")


# --------------------------------------------------------------------
_engine = BuildEngine()
provide = _engine.provide
target = _engine.target
default = _engine.default

# --------------------------------------------------------------------
@dataclass
class BuildConfig:
    name: str = "Default Build"
    watchers: bool = True
    targets: List[str] = field(default_factory=list)
    mode: Mode = Mode.BUILD
    verbose: int = 0
    debug: bool = False
    max_shells: int = multiprocessing.cpu_count()
    force_color: bool = False

    @property
    def parser(self) -> ArgumentParser:
        parser = ArgumentParser(description=self.name, add_help=True)
        parser.add_argument("targets", nargs="*")
        parser.add_argument(
            "--snip",
            "-x",
            dest="mode",
            action="store_const",
            const=Mode.SNIP,
            help="Clean the specified targets.",
        )
        parser.add_argument(
            "--clean",
            "-c",
            dest="mode",
            action="store_const",
            const=Mode.CLEAN,
            help="Clean the specified targets and all of their inputs.",
        )
        parser.add_argument(
            "--rebuild",
            "-R",
            dest="mode",
            action="store_const",
            const=Mode.REBUILD,
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
            const=Mode.LIST_TARGETS,
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
            help="Set the max number of simultaneous live commands.",
        )
        parser.set_defaults(mode=Mode.BUILD)
        return parser

    def parse_args(self):
        self.parser.parse_args(namespace=self)
        return self


# --------------------------------------------------------------------
def setup_default_watcher(build: Recipe, config: BuildConfig = BuildConfig()):
    def _watcher(event_data: EventData):
        def p(tag_color, s=event_data.content, text_color=lambda s: s):
            if sys.stdout.isatty():
                clreol()
            if event_data.event == Event.ERROR and isinstance(s, Exception):
                exc = s
                s = "%s: %s" % (type(exc).__name__, str(exc))
                if config.debug:
                    s += "\n" + "".join(traceback.format_tb(exc.__traceback__))
            print(f"[{tag_color(event_data.recipe.name)}] {text_color(s)}")

        WATCHER_EVENT_MAP = {
            Event.CLEAN: lambda: p(_ok),
            Event.ERROR: lambda: p(_error),
            Event.WARNING: lambda: p(_warning, text_color=_info),
            Event.INFO: lambda: p(_info, text_color=_info),
            Event.START: lambda: p(_start, text_color=_info),
            Event.SUCCESS: lambda: p(_ok, "ok"),
        }

        if config.debug:
            WATCHER_EVENT_MAP[Event.DEBUG] = lambda: p(_debug)

        WATCHER_EVENT_MAP.get(event_data.event, lambda: None)()

    if config.watchers:
        build.watch(_watcher)


# --------------------------------------------------------------------
def _print_targets(engine: BuildEngine, config: BuildConfig):
    recipe_map = engine.load_targetable_recipe_map()
    target_set = set(engine.targets)

    if engine.default_target is not None:
        print("%s (default)" % engine.default_target)

    for target in sorted(target_set):
        if target != engine.default_target:
            print(target)

    if config.verbose:
        for target in sorted(recipe_map.keys()):
            if target not in target_set:
                print(_info(target))


# --------------------------------------------------------------------
def _build(engine: BuildEngine, config: BuildConfig):
    build = engine.create(config.targets)
    setup_default_watcher(build, config)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(build.resolve(), build.spin()))


# --------------------------------------------------------------------
def _clean(engine: BuildEngine, config: BuildConfig):
    build = engine.create(config.targets)
    setup_default_watcher(build, config)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        build.cleanup(
            CleanupMode.RECURSIVE if config.mode == Mode.CLEAN else CleanupMode.RECIPE
        )
    )


# --------------------------------------------------------------------
def _rebuild(engine: BuildEngine, config: BuildConfig):
    build = engine.create(config.targets)
    setup_default_watcher(build, config)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(build.cleanup())
    loop.run_until_complete(asyncio.gather(build.resolve(), build.spin()))


# --------------------------------------------------------------------
BUILD_COMMAND_MAP = {
    Mode.LIST_TARGETS: _print_targets,
    Mode.BUILD: _build,
    Mode.REBUILD: _rebuild,
    Mode.SNIP: _clean,
    Mode.CLEAN: _clean,
}

# --------------------------------------------------------------------
def factory(f):
    def wrapper(*args, **kwargs):
        return f(*args, **kwargs).with_type(f.__name__)

    return wrapper


# --------------------------------------------------------------------
def recipe(f):
    print("xeno.build: @recipe is deprecated, switch to @factory.", file=sys.stderr)
    return factory(f)


# --------------------------------------------------------------------
def build(*, engine: BuildEngine = _engine, name="xeno.build script", watchers=True):
    config = BuildConfig(name, watchers).parse_args()
    if config.force_color:
        enable_color()
    try:
        command = BUILD_COMMAND_MAP[config.mode]
        command(engine, config)
    except AssertionError as e:
        print(f"[{color('SCRIPT ERROR', bg='red', fg='white')}] {e}")
        if config.debug:
            traceback.print_exc()
