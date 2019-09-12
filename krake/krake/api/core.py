from krake.apidefs.core import core
from .generator import generate_api


@generate_api(core)
class CoreApi:
    pass
