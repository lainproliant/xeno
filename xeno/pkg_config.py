# --------------------------------------------------------------------
# pkg_config.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Saturday March 4, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

from xeno.shell import Environment, check


# --------------------------------------------------------------------
def pkg_config(names: str | list[str], static=False) -> Environment:
    env = Environment()
    if isinstance(names, str):
        names = [names]
    for name in names:
        env.append(PackageConfig(name, static=static))
    return env


# --------------------------------------------------------------------
class PackageConfig(Environment):
    """
    An environment wrapper providing build information sourced from pkgconf(1).
    """

    def __init__(self, name: str, static=False):
        self.name = name
        self.static = static
        check(["pkgconf", "--exists", self.name])
        self.cflags = self._get_cflags()
        self.ldflags = self._get_ldflags()
        self.version = self._get_version()
        self["LDFLAGS"] = self.ldflags
        self["CFLAGS"] = self.cflags

    def _get_cflags(self):
        argv = ["pkgconf", "--cflags", self.name]
        if self.static:
            argv.append("--static")

        return check(argv)

    def _get_ldflags(self):
        argv = ["pkgconf", "--libs", self.name]
        if self.static:
            argv.append("--static")

        return check(argv)

    def _get_version(self):
        return check(["pkgconf", "--modversion", self.name]).strip()
