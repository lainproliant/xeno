#!/usr/bin/env python
# --------------------------------------------------------------------
# recipes/__init__.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Monday August 28, 2023
#
# Distributed under terms of the MIT license.
# -------------------------------------------------------------------

import ast

from pathlib import Path
from typing import Collection, Optional

from xeno.recipe import Recipe, recipe
from xeno.recipes.shell import sh
from xeno.shell import select_env
from xeno.typedefs import PathSpec

# -------------------------------------------------------------------
INSTALL_ENV = select_env(append="PREFIX,DESTDIR", PREFIX="usr/local", DESTDIR="/")
TEST_ENV = select_env()


# -------------------------------------------------------------------
@recipe(factory=True, sigil=lambda r: f"{r.name}:{r.target.name}")
def install(program: Recipe, env=INSTALL_ENV):
    root = env.get("DESTDIR", "/")
    prefix = env.get("PREFIX", "/usr/local")

    path = Path(root) / prefix / "bin" / program.target.name
    return sh(
        "mkdir -p {DESTDIR}{PREFIX}/bin; "
        "cp -f {program} {target}; "
        "chmod 775 {target}",
        env=env,
        program=program,
        target=path,
        as_user="root",
    )


# -------------------------------------------------------------------
@recipe(factory=True, sigil=lambda r: f"{r.name}:{r.arg('t').target.name}")
def test(t, env=TEST_ENV, interactive: Collection[str] = set()):
    result = sh(
        t.target,
        t=t,
        env=env,
        interactive=t.name in interactive,
    )
    return result


# -------------------------------------------------------------------
@recipe
async def repo_deps(repo):
    build_script = Path(repo) / 'build.py'
    if not build_script.exists():
        return 0

    with open(build_script, "r") as infile:
        tree = ast.parse(infile.read())

    def has_xeno_imports():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith('xeno'):
                        return True
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith('xeno'):
                    return True
        return False

    if has_xeno_imports():
        return await sh('./build.py deps', repo=repo, cwd=repo, check=True).make()

    return 0


# -------------------------------------------------------------------
@recipe(
    factory=True, sigil=lambda r: f"{r.name}:{r.arg('repo').target.name.split('/')[-1]}"
)
def checkout(repo, target: Optional[PathSpec] = None):
    name = repo.split("/")[-1]
    target = target or Path("deps") / name
    return repo_deps(
        sh(["git", "clone", "{repo}", "{target}"], repo=repo, target=target)
    )
