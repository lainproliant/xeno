#!/usr/bin/env python
# --------------------------------------------------------------------
# recipes/__init__.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Monday August 28, 2023
#
# Distributed under terms of the MIT license.
# -------------------------------------------------------------------

from pathlib import Path
from typing import Collection
from xeno.recipe import Recipe, recipe
from xeno.shell import select_env
from xeno.recipes.shell import sh


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
@recipe(factory=True)
def repo_deps(repo):
    return sh("[[ ! -f build.py ]] || ./build.py deps", repo=repo, cwd=repo.target)


# -------------------------------------------------------------------
@recipe(factory=True, sigil=lambda r: f"{r.name}:{r.arg('repo').target.name.split('/')[-1]}")
def checkout(repo):
    name = repo.split("/")[-1]
    return repo_deps(
        sh("git clone {repo} {target}", repo=repo, target=Path("deps") / name)
    )
