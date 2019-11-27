import logging
from aiohttp import web

from krake.apidefs.openstack import openstack
from krake.data.openstack import MagnumCluster, MagnumClusterBinding
from .generator import generate_api
from .auth import protected
from .helpers import use_schema, load, session


logger = logging.getLogger("krake.api.kubernetes")


@generate_api(openstack)
class OpenStackApi:
    @protected(api="openstack", resource="magnumclusters/binding", verb="update")
    @load("cluster", MagnumCluster)
    @use_schema("body", MagnumClusterBinding.Schema)
    async def update_magnum_cluster_binding(request, body, cluster):
        cluster.status.project = body.project
        cluster.status.template = body.template

        if body.project not in cluster.metadata.owners:
            cluster.metadata.owners.append(body.project)

        await session(request).put(cluster)
        logger.info("Bind %r to %r", cluster, cluster.status.project)
        return web.json_response(cluster.serialize())
