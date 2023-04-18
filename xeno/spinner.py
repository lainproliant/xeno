# --------------------------------------------------------------------
# spinner.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday January 12, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import sys
import asyncio
import itertools
from datetime import datetime, timedelta
from xeno.events import EventBus

from xeno.color import color

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
        shape_array = []

        for shape in DEFAULT_SHAPE:
            shape_array.append(
                "".join(
                    [shape[0], color(shape[1:-1], fg="red", render="dim"), shape[-1]]
                )
            )

        self.message = message
        self.cycle = itertools.cycle(shape_array)
        self.interval = interval
        self.delay = delay
        self.start = datetime.now()

    async def spin(self) -> int:
        if not sys.stdout.isatty():
            return 0

        erase_chars = 0
        if datetime.now() - self.start > timedelta(seconds=self.delay):
            sys.stdout.write("\r")
            erase_chars = sys.stdout.write(
                next(self.cycle) + color(f" {self.message} ", render="dim")
            )
            sys.stdout.flush()
        await asyncio.sleep(self.interval)
        return erase_chars
