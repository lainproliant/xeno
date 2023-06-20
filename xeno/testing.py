# --------------------------------------------------------------------
# testing.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday April 13, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import io
import sys


# --------------------------------------------------------------------
class OutputCapture:
    VALID_TARGETS = set(["stdout", "stderr"])

    def __init__(self, **kwargs):
        self.targets = set()

        for k, v in kwargs.items():
            if k not in OutputCapture.VALID_TARGETS:
                raise ValueError(
                    f"Capture targets must be one or more of {OutputCapture.VALID_TARGETS}."
                )
            if v:
                self.targets.add(k)

        self.stdin = io.StringIO()
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.original_streams: dict[str, io.IOBase] = {}

    def __enter__(self, *args):
        for target in self.targets:
            self.original_streams[target] = getattr(sys, target)
            setattr(sys, target, getattr(self, target))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for target in self.targets:
            setattr(sys, target, self.original_streams[target])
        self.original_streams.clear()
