# --------------------------------------------------------------------
# shell.py
#
# Author: Lain Musgrove (lain.musgrove@hearst.com)
# Date: Sunday August 27, 2023
# --------------------------------------------------------------------
import shlex
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional, cast

from xeno.recipe import Events, Recipe, recipe
from xeno.shell import Environment, PathSpec, Shell
from xeno.utils import is_iterable


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
                return f"{recipe.program_name()}:{recipe.rel_target()}"
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
        cmd,
        *,
        as_user: Optional[str] = None,
        cleanup: Optional[str | list[str]] = None,
        cleanup_cwd: Optional[PathSpec] = None,
        code=0,
        ctrlc=False,
        cwd: Optional[PathSpec | Recipe] = None,
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
        shell_cwd = cwd
        if isinstance(cwd, Recipe):
            shell_cwd = cwd.target

        self.env = Environment.context() if env is None else {**env}
        self.shell = Shell(self.env, shell_cwd)
        self.cmd: str | list[str] = []
        self.cleanup_cmd = cleanup
        self.cleanup_cwd = Path(cleanup_cwd or Path.cwd())

        if cwd:
            # Add 'cwd' to kwargs if specified, as kwargs is used
            # by the scanner to interpolate keyword args into
            # commands and determine dependencies.
            kwargs["cwd"] = cwd

        target = None
        component_list = []

        if Recipe.DEFAULT_TARGET_PARAM in kwargs:
            target = kwargs[Recipe.DEFAULT_TARGET_PARAM]

        def convert_cmd(cmd_comp) -> str:
            if isinstance(cmd_comp, str | Path):
                return str(cmd_comp)

            elif isinstance(cmd_comp, Recipe):
                assert (
                    cmd_comp.has_target()
                ), "Recipe without a target can't be used in a shell command."
                component_list.append(cmd_comp)
                target = cmd_comp.rel_target()
                if Path.cwd() == target.parent.absolute():
                    return f"./{target}"
                return str(target)

            else:
                raise ValueError(f"Invalid shell command component: {cmd_comp}")

        if is_iterable(cmd):
            self.cmd = [convert_cmd(c) for c in cmd]
        else:
            self.cmd = convert_cmd(cmd)

        self.expected_code = code
        self.interact = interact
        self.ctrlc = ctrlc
        self.quiet = quiet
        self.redacted = redacted
        self.result_spec = result
        self.scanner = Recipe.scan([], kwargs)
        super().__init__(
            component_list=component_list,
            component_map=self.scanner.component_map(),
            as_user=as_user,
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
        self.stdout_lines.append(line)

    def log_stderr(self, line: str, _):
        if not self.quiet:
            self.log(Events.WARNING, line)
        self.stderr_lines.append(line)

    async def clean(self):
        await super().clean()

        if self.cleanup_cmd:
            self._make_interactive(True)
            if self.return_code != 0:
                raise RuntimeError("Failed to run cleanup command.")

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

    def _make_interactive(self, cleanup=False):
        shell = self.shell

        if cleanup:
            cmd = self.cleanup_cmd
            shell = shell.cd(self.cleanup_cwd)
            pass_mode = Recipe.PassMode.TARGETS
        else:
            cmd = self.cmd
            pass_mode = Recipe.PassMode.RESULTS

        assert cmd

        kwargs = self.scanner.kwargs(pass_mode)
        if self.as_user:
            self.return_code = shell.interact_as(
                self.as_user, cmd, ctrlc=self.ctrlc, **kwargs
            )
        else:
            self.return_code = shell.interact(cmd, ctrlc=self.ctrlc, **kwargs)

    def _get_result(self, spec: Result):
        match spec:
            case ShellRecipe.Result.CODE:
                return self.return_code
            case ShellRecipe.Result.FILE:
                return self.target
            case ShellRecipe.Result.STDOUT:
                result = self.stdout_lines
                self.stdout_lines = []
                return result
            case ShellRecipe.Result.STDERR:
                result = self.stderr_lines
                self.stderr_lines = []
                return result

    def _compute_result(self):
        if self.result_spec is None:
            return self._get_result(
                ShellRecipe.Result.FILE
                if self.has_target()
                else ShellRecipe.Result.CODE
            )

        if isinstance(self.result_spec, ShellRecipe.Result):
            return self._get_result(self.result_spec)

        return [self._get_result(r) for r in self.result_spec]


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
