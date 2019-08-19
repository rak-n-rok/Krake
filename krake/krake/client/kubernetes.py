from krake.apidefs.kubernetes import kubernetes
from .generator import generate_client


@generate_client(kubernetes)
class KubernetesApi:
    pass
