# --------------------------------------------------------------------
# color.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Wednesday October 28, 2020
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------
import os
from functools import partial

from colors import color as _color

# --------------------------------------------------------------------
_ansi_enabled = "NO_COLOR" not in os.environ

# --------------------------------------------------------------------
color = partial(_color) if _ansi_enabled else partial(lambda *args, **kwargs: args[0])
