# --------------------------------------------------------------------
# shell.py
#
# Author: Lain Musgrove (lain.musgrove@hearst.com)
# Date: Sunday August 27, 2023
# --------------------------------------------------------------------
import shlex
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional, Union, cast

from xeno.recipe import Events, Recipe, recipe
from xeno.shell import Environment, PathSpec, Shell


# --------------------------------------------------------------------
class ShellRecipe(Recipe):
    class Result(Enum):
        CODE = 0
        STDOUT = 1
        STDERR = 2
        FILE = 3

    ResultSpec = Iterable[Result] | Result

    class Format(Recipe.Format):
        def sigil(self, recipe: Recipe) -> str:
            assert isinstance(recipe, ShellRecipe)
            recipe = cast(ShellRecipe, recipe)
            if recipe.has_target():
                return f"{recipe.program_name()}:{recipe.rtarget()}"
            else:
                return f"{recipe.program_name()}"

        def start(self, recipe: Recipe) -> str:
            assert isinstance(recipe, ShellRecipe)
            recipe = cast(ShellRecipe, recipe)
            cmd = recipe.shell.interpolate(
                recipe.cmd, recipe.scanner.kwargs(Recipe.PassMode.TARGETS)
            )
            return cmd

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
        quiet=False,
        result: Optional["ShellRecipe.ResultSpec"] = None,
        redacted: set[str] = set(),
        sync=False,
        **kwargs,
    ):
        self.env = (
            Environment.context() if env is None else {**Environment.context(), **env}
        )
        self.shell = Shell(self.env, cwd)

        target = None

        if Recipe.DEFAULT_TARGET_PARAM in kwargs:
            target = kwargs[Recipe.DEFAULT_TARGET_PARAM]

        self.as_user = as_user
        self.cmd: list[str] | str = (
            str(cmd) if isinstance(cmd, str | Path) else list(cmd)
        )
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
            name=name,
            fmt=ShellRecipe.Format(),
            static_files=self.scanner.paths(),
            sync=sync,
            target=target,
        )

        self.name = self.name or self.program_name()

        self.return_code: Optional[int] = None
        self.stdout_lines: list[str] = []
        self.stderr_lines: list[str] = []

    def program_name(self):
        if isinstance(self.cmd, list):
            cmd = self.cmd[0]
        else:
            cmd = shlex.split(self.cmd)[0]
        try:
            cmd = str(Path(cmd).relative_to(Path.cwd()))
        except ValueError:
            pass
        return self.shell.interpolate(cmd, {})

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
            if self.has_target():
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
        kwargs["env"] = {**sh.env, **kwargs["env"]}
    elif sh.env:
        kwargs["env"] = sh.env
    return ShellRecipe(cmd, **kwargs)


# --------------------------------------------------------------------
sh.env = {}
sh.result = ShellRecipe.Result
