from krake.apidefs.openstack import openstack
from .generator import generate_api


@generate_api(openstack)
class OpenStackApi:
    pass
