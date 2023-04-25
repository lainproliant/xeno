# --------------------------------------------------------------------
# spinner.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday January 12, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
import itertools
import sys
from datetime import datetime, timedelta
from typing import Iterable, Optional

from xeno.color import color, is_enabled as is_color_enabled

DEFAULT_SHAPE = [
    "[=   ]",
    "[==  ]",
    "[=== ]",
    "[====]",
    "[ ===]",
    "[  ==]",
    "[   =]",
    "[    ]",
]


class Spinner:
    def __init__(self, message: str, interval: float = 0.05, delay: float = 0.25):
        self.message = message
        self.colorized = is_color_enabled
        self.cycle: Optional[Iterable[str]] = None
        self.interval = interval
        self.delay = delay
        self.start = datetime.now()

    def _setup_cycle(self):
        shape_array = []

        if self.colorized:
            for shape in DEFAULT_SHAPE:
                shape_array.append(
                    "".join(
                        [
                            shape[0],
                            color(shape[1:-1], fg="yellow"),
                            shape[-1],
                        ]
                    )
                )
        else:
            for shape in DEFAULT_SHAPE:
                shape_array.extend(DEFAULT_SHAPE)

        self.cycle = itertools.cycle(shape_array)

    async def spin(self) -> int:
        if not sys.stdout.isatty():
            return 0

        if not self.cycle:
            self._setup_cycle()

        assert self.cycle is not None

        erase_chars = 0
        if datetime.now() - self.start > timedelta(seconds=self.delay):
            sys.stdout.write("\r")
            erase_chars = sys.stdout.write(
                next(self.cycle) + color(f" {self.message} ", render="dim")
            )
            sys.stdout.flush()
        await asyncio.sleep(self.interval)
        return erase_chars
