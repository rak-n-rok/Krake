from krake.apidefs.core import core
from .generator import generate_client


@generate_client(core)
class CoreApi:
    pass
