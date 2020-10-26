# --------------------------------------------------------------------
# build.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Sunday October 18, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
import os
import shlex
import shutil
import multiprocessing

from argparse import ArgumentParser
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional

from xeno import Injector, MethodAttributes
from xeno.shell import EnvDict, Shell
from xeno.utils import async_wrap, is_iterable

# --------------------------------------------------------------------
TARGET_ATTR = "xeno.build.target"
DEFAULT_ATTR = "xeno.build.default"

# --------------------------------------------------------------------
class Event(Enum):
    START = "start"
    INFO = "info"
    ERROR = "error"
    FAILURE = "failure"
    SUCCESS = "success"
    CLEANING = "cleaning"
    CLEAN = "clean"


# --------------------------------------------------------------------
class Mode(Enum):
    BUILD = "build"
    CLEAN = "clean"
    PURGE = "purge"
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
    """ A recipe represents a repeatable action which may be reversible. """

    def __init__(
        self,
        name: Optional[str] = None,
        input: Optional[Iterable["Recipe"]] = None,
        synchronous=False,
    ):
        self.name = name or self.__class__.__name__
        self.inputs = list(input or [])
        self.synchronous = synchronous
        self.watchers: List[EventWatcher] = []
        self.origin: Optional[str] = None
        self.lock = asyncio.Lock()

    def watch(self, watcher: EventWatcher):
        self.watchers.append(watcher)
        for input in self.inputs:
            input.watch(watcher)

    def trigger(self, event: Event, content: Any = None) -> EventData:
        event_data = EventData(event, self, content)
        for watcher in self.watchers:
            watcher(event_data)
        return event_data

    async def resolve(self):
        async with self.lock:
            try:
                assert self.ready
                if self.synchronous:
                    for recipe in self.inputs:
                        await recipe.resolve()
                else:
                    await asyncio.gather(*(recipe.resolve() for recipe in self.inputs))

                assert all(
                    recipe.done for recipe in self.inputs
                ), "Not all recipe inputs are done."
                self.trigger(Event.START)
                await self.make()
                assert self.done, "Recipe is not done after make."
                self.trigger(Event.SUCCESS)

            except Exception as e:
                self.trigger(Event.FAILURE, e)

    async def make(self):
        """ Generate the final recipe result once all inputs are done. """
        pass

    async def clean(self):
        """ Clean the final recipe result. """
        pass

    async def cleanup(self, mode: CleanupMode = CleanupMode.RECURSIVE):
        """ Cleanup the final result and all input results.  """
        async with self.lock:
            if self.dirty:
                self.trigger(Event.CLEANING)
                await self.clean()

                if mode == CleanupMode.SHALLOW:
                    for recipe in self.inputs:
                        await recipe.cleanup(CleanupMode.RECIPE)

                elif mode == CleanupMode.RECURSIVE:
                    for recipe in self.inputs:
                        await recipe.cleanup(CleanupMode.RECURSIVE)

                elif mode != CleanupMode.RECIPE:
                    raise ValueError("Invalid cleanup mode specified.")

            self.trigger(Event.CLEAN)

    @property
    def result(self):
        """ The result of the recipe.  Defaults to the result of all inputs. """
        return [recipe.result for recipe in self.inputs]

    @property
    def ready(self):
        """ Determine if prerequisites are met for this recipe. """
        return True

    @property
    def done(self):
        """ Whether the full result of this recipe exists. """
        return False

    @property
    def dirty(self):
        """ Whether the full or partial result of this recipe exists. """
        return self.done or any(recipe.dirty for recipe in self.inputs)

    def tokenize(self) -> List[str]:
        """ Generate a list of tokens from the value for command interpolation. """
        tokens: List[str] = []
        if is_iterable(self.result):
            tokens.extend(self.result)
        else:
            tokens.append(self.result)
        assert all(
            isinstance(token, str) for token in tokens
        ), "One or more tokens are not strings."
        return tokens

    def __str__(self):
        return " ".join(shlex.quote(s) for s in self.tokenize())


# --------------------------------------------------------------------
class FileRecipe(Recipe):
    def __init__(
        self,
        output: Path,
        input: Optional[Iterable[Recipe]],
        requires: Optional[Iterable[Path]],
    ):
        super().__init__(output.name, input)
        self.output = output
        self.requires = list(requires or [])

    async def resolve(self):
        for path in self.requires:
            assert path.exists()
        await super().resolve()

    @property
    def ready(self):
        return all(path.exists() for path in self.requires)

    @property
    def done(self):
        """ Whether the full result of this recipe exists. """
        return self.output.exists()

    async def clean(self):
        if not self.output.exists():
            return

        if self.output.is_dir():
            shutil.rmtree(self.output)
        else:
            self.output.unlink()

    async def make(self):
        """ Abstract method: generate the file once all inputs are done. """
        raise NotImplementedError()


# --------------------------------------------------------------------
class ShellRecipeMixin:
    @staticmethod
    def log_stdout(line: str, recipe: Recipe):
        recipe.trigger(Event.INFO, line)

    @staticmethod
    def log_stderr(line: str, recipe: Recipe):
        recipe.trigger(Event.ERROR, line)

    shell: Shell
    cmd: str
    params: EnvDict
    require_success: bool
    returncode: Optional[int]

    def shell_mixin_init(
        self, cmd: str, env: Optional[EnvDict], require_success=True, **params
    ):
        self.shell = Shell({**os.environ, **(env or {})})
        self.cmd = cmd
        self.params = params
        self.require_success = require_success

    async def make(self):
        self.returncode = await self.shell.run(
            self.cmd,
            stdout=ShellFileRecipe.log_stdout,
            stderr=ShellFileRecipe.log_stderr,
            **self._merge_params()
        )
        assert self.returncode == 0 or not self.require_success, "Command failed."

    def _merge_params(self) -> EnvDict:
        return self.params


# --------------------------------------------------------------------
class ShellRecipe(Recipe, ShellRecipeMixin):
    def __init__(
        self,
        cmd: str,
        env: Optional[EnvDict],
        input: Optional[Iterable[Recipe]],
        require_success=True,
        **params
    ):
        super().__init__(shlex.split(cmd)[0], input)
        self.shell_mixin_init(cmd, env, require_success, **params)

    @property
    def done(self):
        return (
            self.returncode == 0
            if self.require_success
            else self.returncode is not None
        )


# --------------------------------------------------------------------
class ShellFileRecipe(FileRecipe, ShellRecipeMixin):
    def __init__(
        self,
        cmd: str,
        output: Path,
        env: Optional[EnvDict],
        input: Optional[Iterable[Recipe]],
        requires: Optional[Iterable[Path]],
        require_success=True,
        **params
    ):
        super().__init__(output, input, requires)
        self.shell_mixin_init(cmd, env, require_success, **params)

    def _merge_params(self) -> EnvDict:
        return {
            **self.params,
            "output": self.output,
            "input": self.inputs,
            "requirements": self.requires,
        }


# --------------------------------------------------------------------
def sh(*args, **kwargs) -> Recipe:
    if "output" in kwargs:
        return ShellFileRecipe(*args, **kwargs)
    return ShellRecipe(*args, **kwargs)


# --------------------------------------------------------------------
class BuildEngine:
    def __init__(self):
        self._injector = Optional[Injector]

    @property
    def injector(self) -> Injector:
        if self._injector is None:
            self._injector = Injector()
        return self._injector

    @property
    def targets(self) -> List[str]:
        return [
            k for k, v in self.injector.scan_resources(lambda k, v: k == TARGET_ATTR)
        ]

    @property
    def default_target(self) -> Optional[str]:
        results = [
            k for k, v in self.injector.scan_resources(lambda k, v: k == DEFAULT_ATTR)
        ]
        assert len(results) <= 1, "More than one default target specified."
        return results[0] if results else None

    def provide(self, f):
        self.injector.provide(f, is_singleton=True)

    def target(self, f):
        @MethodAttributes.wraps(f)
        async def wrapper(*args, **kwargs):
            result = await async_wrap(f, *args, **kwargs)
            assert result is not None, "Target definition didn't return a value."
            if is_iterable(result):
                results = list(result)
                assert all(
                    isinstance(obj, Recipe) for obj in results
                ), "Target definition returned an iterable containing non-Recipe values."
                result = Recipe(f.__name__, results, isinstance(result, tuple))
            assert isinstance(
                result, Recipe
            ), "Target definition returned a non-Recipe value."
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

    def __call__(self, targets: Optional[Iterable[str]] = None):
        targets = list(targets if targets is not None else [])
        recipes = [self.injector.require(target) for target in targets]
        assert all(
            isinstance(obj, Recipe) for obj in recipes
        ), "One or more target definitions returned a non-Recipe value."
        return Recipe("build", recipes)

# --------------------------------------------------------------------
_engine = BuildEngine()
provide = _engine.provide
target = _engine.target
default = _engine.default

# --------------------------------------------------------------------
def build(*, engine: BuildEngine = _engine, name="xeno.build script"):
    parser = ArgumentParser(description=name, add_help=True)
    parser.add_argument("targets", nargs="*", default=None)
    parser.add_argument("--clean", "-c", dest="mode", action="store_const", const=Mode.CLEAN,
                        help="Clean the specified targets.")
    parser.add_argument("--purge", "-x", dest="mode", action="store_const", const=Mode.PURGE,
                        help="Clean the specified targets and all of their inputs.")
    parser.add_argument("--verbose", "-v", action="count", default=0,
                        help="Print stdout (-v) and/or stderr (-vv) for live running commands.")
    parser.add_argument("--list", "-l", dest="mode", action="store_const", const=Mode.LIST_TARGETS,
                        help="List all defined targets.")
    parser.add_argument("--debug", "-D", action="store_true",
                        help="Print stack traces and other diagnostic info.")
    parser.add_argument("--max", "-m", type=int, default=multiprocessing.cpu_count(),
                        help="Set the max number of simultaneous live commands.")
    parser.set_defaults(mode=Mode.BUILD)

    args = parser.parse_args()

    if args.mode == Mode.LIST_TARGETS:
