# --------------------------------------------------------------------
# typedefs.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Monday August 28, 2023
# --------------------------------------------------------------------

import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, Tuple, Union

# --------------------------------------------------------------------
EnvDict = Dict[str, str] | Dict[str, Any]
InputSource = Callable[[], str]
LineSink = Callable[[str, asyncio.StreamWriter], None]
OutputTaskData = Tuple[asyncio.StreamReader, LineSink]
PathSpec = Union[str | Path]
