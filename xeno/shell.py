# --------------------------------------------------------------------
# shell.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Saturday October 24, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
import os
import shlex
import subprocess
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Set, Tuple, Union

from xeno.utils import decode, is_iterable


# --------------------------------------------------------------------
class Environment(dict[str, Any]):
    """
    An environment dictionary that knows how to append shell
    flag variables together when added to other dictionaries.
    """

    @staticmethod
    def context():
        return Environment(os.environ)

    def __add__(self, rhs: Any) -> "Environment":
        env = Environment()
        for key, value in rhs.items():
            if key in self:
                if not is_iterable(value):
                    value = shlex.split(value)
                env[key] = shlex.join(shlex.split(self[key]) + value)
            else:
                env[key] = value
        return env


# --------------------------------------------------------------------
EnvDict = Environment | Dict[str, Any]
InputSource = Callable[[], str]
LineSink = Callable[[str, asyncio.StreamWriter], None]
OutputTaskData = Tuple[asyncio.StreamReader, LineSink]
PathSpec = Union[str | Path]


# --------------------------------------------------------------------
def digest_env(env: EnvDict):
    flat_env: Dict[str, str] = {}
    for key, value in env.items():
        if is_iterable(value):
            value = " ".join(shlex.quote(str(s)) for s in value)
        flat_env[key] = str(value)
    return flat_env


# --------------------------------------------------------------------
def digest_params(params: EnvDict):
    flat_params: Dict[str, str] = {}
    for key, value in params.items():
        if is_iterable(value):
            value = " ".join(str(s) for s in value)
        flat_params[key] = str(value)
    return flat_params


# --------------------------------------------------------------------
def check(cmd: Union[str, Iterable[str]]):
    if isinstance(cmd, str):
        args = shlex.split(cmd)
    else:
        args = [*cmd]
    return subprocess.check_output(args).decode("utf-8").strip()


# --------------------------------------------------------------------
def remove_paths(*paths: Path, as_user: Optional[str] = None):
    for path in paths:
        if as_user is not None:
            result = Shell().interact_as(as_user, ["rm", "-rf", str(path.absolute())])
            if result != 0:
                raise RuntimeError(f"Failed to remove path `f{path}` as `f{as_user}`.")

        else:
            if not path.exists():
                continue

            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()


# --------------------------------------------------------------------
class Shell:
    max_jobs: int = 0
    job_semaphore: asyncio.Semaphore = asyncio.Semaphore(max_jobs)

    @classmethod
    def set_max_jobs(cls, n: int):
        cls.max_jobs = n
        cls.job_semaphore = asyncio.Semaphore(cls.max_jobs)

    def __init__(self, env: EnvDict = dict(os.environ), cwd: Optional[PathSpec] = None):
        self._env = digest_env(env)
        self._cwd = Path(cwd) if cwd is not None else Path.cwd()

    def env(self, new_env: EnvDict):
        return Shell({**self._env, **new_env}, self._cwd)

    def cd(self, new_cwd: Path):
        assert new_cwd.exists() and new_cwd.is_dir(), "Invalid directory provided."
        return Shell(self._env, new_cwd)

    # pylint: disable=no-member
    # see: https://github.com/PyCQA/pylint/issues/1469
    async def _create_proc(self, cmd: str) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_shell(
            cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
            cwd=self._cwd,
            shell=True,
        )

    def _interact(self, cmd: str, check: bool) -> int:
        returncode = subprocess.call(cmd, env=self._env, cwd=self._cwd, shell=True)
        assert not check or returncode == 0, "Command failed."
        return returncode

    def interpolate(
        self,
        cmd: Union[str, Iterable[str]],
        params: EnvDict,
        wrappers: Dict[str, Callable[[str], str]] = {},
        redacted: Set[str] = set(),
    ) -> str:
        digested_params = {
            k: wrappers[k](v)
            if k in wrappers
            else (wrappers["*"](v) if "*" in wrappers else v)
            for k, v in digest_params(params).items()
        }

        redacted_params = {
            k: v if k not in redacted else "<redacted>"
            for k, v in digested_params.items()
        }

        if isinstance(cmd, str):
            final_cmd = cmd.format(**self._env, **redacted_params)
        else:
            final_cmd = shlex.join(
                [str(c).format(**self._env, **redacted_params) for c in cmd]
            )

        return final_cmd

    async def run(
        self,
        cmd: Union[str, Iterable[str]],
        stdin: Optional[InputSource] = None,
        stdout: Optional[LineSink] = None,
        stderr: Optional[LineSink] = None,
        check=False,
        **params,
    ) -> int:
        async with self.job_semaphore:
            rl_tasks: Dict[asyncio.Future[Any], OutputTaskData] = {}

            def setup_rl_task(stream: asyncio.StreamReader, sink: LineSink):
                rl_tasks[asyncio.Task(stream.readline())] = (stream, sink)

            cmd = self.interpolate(cmd, params)
            proc = await self._create_proc(cmd)
            assert proc.stdout is not None
            assert proc.stderr is not None
            if stdin:
                assert proc.stdin
                proc.stdin.write(stdin().encode("utf-8"))
            if stdout:
                setup_rl_task(proc.stdout, stdout)
            if stderr:
                setup_rl_task(proc.stderr, stderr)

            while rl_tasks:
                done, _ = await asyncio.wait(
                    rl_tasks, return_when=asyncio.FIRST_COMPLETED
                )

                for future in done:
                    stream, sink = rl_tasks.pop(future)
                    line = future.result()
                    if line:
                        line = decode(line).rstrip()
                        assert proc.stdin is not None
                        sink(line, proc.stdin)
                        setup_rl_task(stream, sink)

            await proc.wait()
            assert proc.returncode is not None, "proc.returncode is None"
            assert not check or proc.returncode == 0, "Command failed."
            return proc.returncode

    def sync(
        self,
        cmd: Union[str, Iterable[str]],
        stdin: Optional[InputSource] = None,
        stdout: Optional[LineSink] = None,
        stderr: Optional[LineSink] = None,
        check=False,
        **params,
    ) -> int:
        return asyncio.run(self.run(cmd, stdin, stdout, stderr, check, **params))

    def interact(self, cmd: Union[str, Iterable[str]], check=False, **params) -> int:
        cmd = self.interpolate(cmd, params)
        return self._interact(cmd, check)

    def interact_as(
        self, as_user: str, cmd: Union[str, Iterable[str]], check=False, **params
    ) -> int:
        cmd = self.interpolate(cmd, params)
        cmd = shlex.join(["sudo", "-u", as_user, "sh", "-c", cmd])
        return self._interact(cmd, check)
