from krake.apidefs.openstack import openstack
from .generator import generate_client


@generate_client(openstack)
class OpenStackApi:
    pass
