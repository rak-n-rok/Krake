"""This module provides the Websocket API of the Krake application. It is
implemented as an :mod:`websocket` application.
"""

import os.path
import sys

parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, parent)

from krake.__about__ import (  # noqa: E402
    __version__
)

__version__ = __version__
