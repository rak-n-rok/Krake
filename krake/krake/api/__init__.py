"""This module provides the HTTP RESTful API of the Krake application. It is
implemented as an :mod:`aiohttp` application.
"""

import os.path
import sys

parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent)

from krake.__about__ import (  # noqa: E402
    __version__
)
