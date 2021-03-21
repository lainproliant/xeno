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
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set, Tuple, Union, Iterable

from xeno.utils import decode, is_iterable

# --------------------------------------------------------------------
EnvDict = Dict[str, Any]
InputSource = Callable[[], str]
LineSink = Callable[[str, asyncio.StreamWriter], None]
OutputTaskData = Tuple[asyncio.StreamReader, LineSink]

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
class Shell:
    def __init__(self, env: EnvDict = dict(os.environ), cwd: Optional[Path] = None):
        self._env = digest_env(env)
        self._cwd = cwd or Path.cwd()

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
            return cmd.format(**self._env, **redacted_params)
        else:
            return shlex.join([c.format(**self._env, **redacted_params) for c in cmd])

    async def run(
        self,
        cmd: Union[str, Iterable[str]],
        stdin: Optional[InputSource] = None,
        stdout: Optional[LineSink] = None,
        stderr: Optional[LineSink] = None,
        check=False,
        **params
    ) -> int:

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
            done, pending = await asyncio.wait(
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
        **params
    ) -> int:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(
            self.run(cmd, stdin, stdout, stderr, check, **params)
        )

    def interact(self, cmd: Union[str, Iterable[str]], check=False, **params) -> int:
        cmd = self.interpolate(cmd, params)
        return self._interact(cmd, check)
