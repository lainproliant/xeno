# --------------------------------------------------------------------
# recipe.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Sunday October 18, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

from xeno.utils import is_iterable


# --------------------------------------------------------------------
EnvDict = Dict[str, Union[str, Iterable[str]]]

# --------------------------------------------------------------------
class Recipe:
    """ A recipe represents a repeatable action which may be reversible. """

    def __init__(
        self,
        name: Optional[str] = None,
        steps: Optional[Iterable["Recipe"]] = None,
        synchronous=False,
    ):
        self.name = name or self.__class__.__name__
        self.steps = list(steps or [])
        self.synchronous = synchronous

    async def resolve(self):
        if self.synchronous:
            for step in self.steps:
                await step.resolve()
        else:
            await asyncio.gather(*(step.resolve() for step in self.steps))

        assert all(step.done for step in self.steps), "Not all recipe steps are done."
        await self.make()
        assert self.done, "Recipe is not done after make."

    async def make(self):
        """ Generate the final recipe result once all steps are done. """
        pass

    async def clean(self):
        """ Clean the final recipe result. """
        pass

    async def cleanup(self):
        """ Cleanup the final result and all step results.  """
        await self.clean()
        for step in self.steps:
            await step.cleanup()

    @property
    def result(self):
        """ The result of the recipe.  Defaults to the result of all steps. """
        return [step.result for step in self.steps]

    @property
    def tokenize(self) -> List[str]:
        """ Generate a list of tokens from the value for command interpolation. """
        tokens = []
        if is_iterable(self.result):
            tokens.extend(self.result)
        else:
            tokens.append(self.result)
        assert all(
            isinstance(token, str) for token in tokens
        ), "One or more tokens are not strings."
        return tokens

    @property
    def done(self):
        """ Whether the full result of this recipe exists. """
        return False

    @property
    def dirty(self):
        """ Whether the full or partial result of this recipe exists. """
        return self.done or any(step.dirty for step in self.steps)


# --------------------------------------------------------------------
class FileRecipe(Recipe):
    def __init__(
        self,
        creates: Path,
        steps: Optional[Iterable[Recipe]],
        requires: Optional[Iterable[Path]],
    ):
        super().__init__(creates.name, steps)
        self.creates = creates
        self.requires = list(requires or [])

    async def clean(self):
        if not self.creates.exists():
            return

        if self.creates.is_dir():
            shutil.rmtree(self.creates)
        else:
            self.creates.unlink()

    async def make(self):
        """ Abstract method: generate the file once all steps are done. """
        raise NotImplementedError()
