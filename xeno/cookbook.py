# --------------------------------------------------------------------
# cookbook.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Tuesday April 4, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------
import inspect
import shlex
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Optional, Union, cast, no_type_check

from xeno.attributes import MethodAttributes
from xeno.recipe import Events, Lambda, Recipe
from xeno.shell import Environment, PathSpec, Shell
from xeno.utils import is_iterable


# --------------------------------------------------------------------
def recipe(
    name_or_f: Optional[str | Callable] = None,
    *,
    factory=False,
    keep=False,
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
                if inspect.iscoroutinefunction(f):
                    raise ValueError(
                        "Recipe factories should not be coroutines.  You should define asynchronous behavior in recipes and return these from recipe factories and target definitions instead."
                    )
                result = f(*args, **kwargs)
                if is_iterable(result):
                    result = Recipe(
                        [*result],
                        name=truename,
                        keep=keep,
                        sync=sync,
                        memoize=memoize,
                    )
                else:
                    result = cast(Recipe, result)

                result.sync = sync
                result.keep = keep
                result.memoize = memoize
                result.name = truename
                return result

            return Lambda(
                f,
                [*args],
                {**kwargs},
                name=truename,
                sync=sync,
                keep=keep,
                memoize=memoize,
            )

        return target_wrapper

    if callable(name_or_f):
        return no_type_check(wrapper(name_or_f))

    return no_type_check(cast(Callable[[Callable], Callable], wrapper))


# --------------------------------------------------------------------
class ShellRecipe(Recipe):
    class Result(Enum):
        CODE = 0
        STDOUT = 1
        STDERR = 2
        FILE = 3

    ResultSpec = Iterable[Result] | Result

    def __init__(
        self,
        cmd: Union[str, Iterable[str]],
        *,
        as_user: Optional[str] = None,
        code=0,
        cwd: Optional[PathSpec] = None,
        env: Optional[Environment] = None,
        interact=False,
        memoize=False,
        name: Optional[str] = None,
        target: Optional[PathSpec] = None,
        quiet=False,
        result: Optional["ShellRecipe.ResultSpec"] = None,
        redacted: set[str] = set(),
        sync=False,
        **kwargs,
    ):
        self.env = Environment.context() if env is None else Environment.context() + env
        self.shell = Shell(self.env, cwd)

        if target is not None:
            kwargs = dict(target=target, **kwargs)

        self.as_user = as_user
        self.cmd: list[str] | str = cmd if isinstance(cmd, str) else list(cmd)
        self.expected_code = code
        self.interact = interact
        self.quiet = quiet
        self.redacted = redacted
        self.result_spec = result
        self.scanner = Recipe.scan([], kwargs)
        super().__init__(
            [],
            self.scanner.component_map(),
            memoize=memoize,
            name=name or self.program_name(),
            static_files=self.scanner.paths(),
            sync=sync,
            target=target,
        )

        self.return_code: Optional[int] = None
        self.stdout_lines: list[str] = []
        self.stderr_lines: list[str] = []

    def program_name(self):
        if isinstance(self.cmd, list):
            return self.cmd[0]
        return shlex.split(self.cmd)[0]

    def log_stdout(self, line: str, _):
        if not self.quiet:
            self.log(Events.INFO, line)

    def log_stderr(self, line: str, _):
        if not self.quiet:
            self.log(Events.WARNING, line)

    async def make(self):
        self.return_code = None
        self.stdout_lines.clear()
        self.stderr_lines.clear()

        if self.interact or self.as_user:
            # Do interactive mode so we can `sudo`.
            self._make_interactive()

        else:
            self.return_code = await self.shell.run(
                self.cmd,
                stdout=self.log_stdout,
                stderr=self.log_stderr,
                **self.scanner.kwargs(Recipe.PassMode.RESULTS),
            )

        assert (
            self.return_code == self.expected_code
        ), f"Unexpected return code.  (expected {self.expected_code}, got {self.return_code})"

        return self._compute_result()

    def _make_interactive(self):
        kwargs = self.scanner.kwargs(Recipe.PassMode.RESULTS)
        if self.as_user:
            self.return_code = self.shell.interact_as(self.as_user, self.cmd, **kwargs)
        else:
            self.return_code = self.shell.interact(self.cmd, **kwargs)

    def _compute_one_result(self, spec: Result):
        match spec:
            case ShellRecipe.Result.CODE:
                return self.return_code
            case ShellRecipe.Result.FILE:
                return self.target
            case ShellRecipe.Result.STDOUT:
                return self.stdout_lines
            case ShellRecipe.Result.STDERR:
                return self.stderr_lines

    def _compute_result(self):
        if self.result_spec is None:
            if self.target is not None:
                result = ShellRecipe.Result.FILE
            else:
                result = ShellRecipe.Result.CODE

            return self._compute_one_result(result)

        if isinstance(self.result_spec, ShellRecipe.Result):
            return self._compute_one_result(self.result_spec)

        return [self._compute_one_result(r) for r in self.result_spec]


# --------------------------------------------------------------------
@recipe(factory=True)
def sh(
    cmd,
    **kwargs,
):
    if "env" in kwargs:
        kwargs["env"] = sh.env + kwargs["env"]
    elif sh.env:
        kwargs["env"] = sh.env
    return ShellRecipe(cmd, **kwargs)


# --------------------------------------------------------------------
sh.env = {}
sh.result = ShellRecipe.Result