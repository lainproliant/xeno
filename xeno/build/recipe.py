# --------------------------------------------------------------------
# recipe.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Sunday October 18, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
from typing import List, Optional

from ..utils import is_iterable


# --------------------------------------------------------------------
class Recipe:
    """ A recipe represents a repeatable action which may be reversible. """

    def __init__(self, name: Optional[str] = None):
        self.name = name or self.__class__.__name__

    async def make(self):
        """ Abstract method: generate the recipe result. """
        raise NotImplementedError()

    async def cleanup(self):
        """ Cleanup the recipe result. """
        pass

    @property
    def result(self):
        """ Abstract property: the result of the recipe. """
        raise NotImplementedError()

    @property
    def tokenize(self) -> List[str]:
        """ Generate a list of tokens from the value for command interpolation. """
        if is_iterable(self.result):
            return list(self.result)
        return [self.result]

    @property
    def exists(self):
        """ Whether the full result of this recipe exists. """
        return False

    @property
    def dirty(self):
        """ Whether the full or partial result of this recipe exists. """
        return True


# --------------------------------------------------------------------
class PolyRecipe(Recipe):
    def __init__(self, members: List[Recipe], synchronous=False):
        self._members = members
        self._synchronous = synchronous

    async def make(self):
        if self._synchronous:
            for member in self._members:
                await member.make()
        else:
            await asyncio.gather(*(m.make() for m in self._members))

    async def cleanup(self):
        for member in self._members:
            await member.cleanup()

    @property
    def result(self):
        return [m.result for m in self._members]

    @property
    def exists(self):
        return all(m.exists for m in self._members)

    @property
    def dirty(self):
        return any(m.dirty for m in self._members)
