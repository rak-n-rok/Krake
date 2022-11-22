import logging
import multiprocessing
import time

import sys
import pytest
import pytz
import asyncio
from asyncio.subprocess import PIPE, STDOUT
from contextlib import suppress
from unittest.mock import MagicMock
from textwrap import dedent
from aiohttp import web

from OpenSSL import crypto

import magnumclient.exceptions

from krake.api.app import create_app
from krake.api.middlewares import error_log
from krake.client import Client
from krake.test_utils import server_endpoint, with_timeout
from krake.data.core import resource_ref, ReasonCode
from krake.data.openstack import MagnumCluster, MagnumClusterState
from krake.data.kubernetes import Cluster
from krake.controller.magnum import MagnumClusterController, main

from tests.factories.openstack import ProjectFactory, MagnumClusterFactory
from tests.factories.kubernetes import ClusterFactory as KubernetesClusterFactory
from tests.factories import fake


@with_timeout(3)
async def test_main_help(loop):
    """Verify that the help for the Magnum Controller is displayed, and contains the
    elements added by the argparse formatters (default value and expected types of the
    parameters).
    """
    command = "python -m krake.controller.magnum -h"
    # The loop parameter is mandatory otherwise the test fails if started with others.
    process = await asyncio.create_subprocess_exec(
        *command.split(" "), stdout=PIPE, stderr=STDOUT
    )
    stdout, _ = await process.communicate()
    output = stdout.decode()

    to_check = [
        "OpenStack Magnum controller",
        "usage:",
        "default:",  # Present if the default value of the arguments are displayed
        "str",  # Present if the type of the arguments are displayed
        "int",
    ]
    # Because python3.10 argparse version changed 'optional arguments:' to 'options:'
    if sys.version_info < (3, 10):
        to_check.append("optional arguments:")
    else:
        to_check.append("options:")

    for expression in to_check:
        assert expression in output


@pytest.mark.slow
def test_main(magnum_config, log_to_file_config):
    """Test the main function of the Magnum Controller, and verify that it starts,
    display the right output and stops without issue.
    """
    log_config, file_path = log_to_file_config()

    magnum_config.api_endpoint = "http://my-krake-api:1234"
    magnum_config.log = log_config

    def wrapper(configuration):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        main(configuration)

    # Start the process and let it time to initialize
    process = multiprocessing.Process(target=wrapper, args=(magnum_config,))
    process.start()
    time.sleep(2)

    # Stop and wait for the process to finish
    process.terminate()
    process.join()

    assert not process.is_alive()
    assert process.exitcode == 0

    # Verify the output of the process
    with open(file_path, "r") as f:
        output = f.read()

    assert "Controller started" in output
    assert "Received signal, exiting..." in output
    assert "Controller stopped" in output

    # Verify that all "ERROR" lines in the output are only errors that logs the lack of
    # connectivity to the API.
    attempted_connectivity = False
    for line in output.split("\n"):
        if "ERROR" in output:
            message = (
                f"In line {line!r}, an error occurred which was different from the"
                f" error from connecting to the API."
            )
            assert "Cannot connect to host my-krake-api:1234" in output, message
            attempted_connectivity = True

    assert attempted_connectivity


def make_openstack_app(cluster_responses):
    ca = crypto.load_certificate(
        crypto.FILETYPE_PEM,
        dedent(
            """
        -----BEGIN CERTIFICATE-----
        MIIDazCCAlOgAwIBAgIUWQEpeoC4tNkpA2opUbq6VlzTIwowDQYJKoZIhvcNAQEL
        BQAwRTELMAkGA1UEBhMCQVUxEzARBgNVBAgMClNvbWUtU3RhdGUxITAfBgNVBAoM
        GEludGVybmV0IFdpZGdpdHMgUHR5IEx0ZDAeFw0xOTExMTkxMDI4MzZaFw0xOTEy
        MTkxMDI4MzZaMEUxCzAJBgNVBAYTAkFVMRMwEQYDVQQIDApTb21lLVN0YXRlMSEw
        HwYDVQQKDBhJbnRlcm5ldCBXaWRnaXRzIFB0eSBMdGQwggEiMA0GCSqGSIb3DQEB
        AQUAA4IBDwAwggEKAoIBAQCcgy+SLUecpFonl1BgCO7hlBDHEXM539M7uaLYFABZ
        Od/xwf6LTrO0az/ehxs1Wx3BIhmThv4qLQHzT84CYtFJeFLz5POQGMFyMABd6TTG
        fJ2/pLUri9ImnpB/HPWUS4ep5iF3zo6ddKQWBEZkvBTbOvQLRv0xdkZCacnebazZ
        2LdQHovrHJw97eIWv1Tnp2OBNHHA74UaV1e8dFyOvHQS6eLzBIePFVCMiTTwPu24
        WMnZ8V8zWeVO9yxhwXfLaBdfNrmgErnSGb4XzbIgcJJfo5aUIqS9q6br64fqg3KX
        ztIzCgC8hv1ZOsHLfhOn/3rAtm8jhbQYVAEXdu/iyy7jAgMBAAGjUzBRMB0GA1Ud
        DgQWBBRiq69K8hrume/gGq8cbeJMTqRwaDAfBgNVHSMEGDAWgBRiq69K8hrume/g
        Gq8cbeJMTqRwaDAPBgNVHRMBAf8EBTADAQH/MA0GCSqGSIb3DQEBCwUAA4IBAQB4
        jGqN4TAHRRu5wWwneQjB8Qq8/5DGHxsUC8TeBQ5ZJG3jserHEf1DMQ/JC5KiG9Dk
        3Qs1D+92hO/LkVt34dIqFkFIuzshFw1FxZGtXRbvHjuDAlAdRb41F4iSTs1V4oiI
        cb7TxaIZZN++7rlEI22znxOsM3qd3AasoKfBGb/SjfEvV0/IOY477O3CqbYH+jK1
        zYZLNdzsksGJU6vNYYBFbNNSWcQOUFE0f0DYvr0TM8fFplpwCxZBiwK67ywYUdwG
        ps2lAT2/EbQpzOIh1b5ROzBQmcFFNAxpkRq/c4AdSK6PiwCDgdo0VhXxgXzyLlOG
        ZrS+c6go0ZV7JOIqRWIq
        -----END CERTIFICATE-----
        """
        ).encode(),
    )
    ca_key = crypto.load_privatekey(
        crypto.FILETYPE_PEM,
        dedent(
            """
        -----BEGIN PRIVATE KEY-----
        MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCcgy+SLUecpFon
        l1BgCO7hlBDHEXM539M7uaLYFABZOd/xwf6LTrO0az/ehxs1Wx3BIhmThv4qLQHz
        T84CYtFJeFLz5POQGMFyMABd6TTGfJ2/pLUri9ImnpB/HPWUS4ep5iF3zo6ddKQW
        BEZkvBTbOvQLRv0xdkZCacnebazZ2LdQHovrHJw97eIWv1Tnp2OBNHHA74UaV1e8
        dFyOvHQS6eLzBIePFVCMiTTwPu24WMnZ8V8zWeVO9yxhwXfLaBdfNrmgErnSGb4X
        zbIgcJJfo5aUIqS9q6br64fqg3KXztIzCgC8hv1ZOsHLfhOn/3rAtm8jhbQYVAEX
        du/iyy7jAgMBAAECggEAeFbNvuEdzKz5vLM1U4HK2psUA1vBcuBL9AIZ2XYXhoNf
        Uu1MICSVO8WyyBCttOqoCBWGAM6sohUVCNV1mpQMQydG8Mw7EbJXGssZnRtwPqUW
        TYIA4siQ/qywgWvszub8GoAdf5bMRPioKV2EGnQavS2o8vrUNrGv9+SLGIDPhHdP
        IvumQ5W35XvMM5oyslSo/VoYpKhzwR800rPe0Tc9h5f5ElWA7R/FIRaLbMqdr5bF
        7qiJFHhXfbozgt+A42HXPJnidfLJZpvvdmR8qUy+2FOImAPMgeVOVGB1a0tEwffN
        TeUpxq0GPzd5NQG1Twux4hgXYWAnHFO56i//oQAiIQKBgQDNJnK3pTFI8Z7nzxBd
        1SmzYgz0g/ahprXQXImb+FedwOPsFGpp5bNttSQLyBZXxxNkhwzEVXX9aBz2GwGX
        BSjLZj46Qcq9wgCGpZmcMi358zdgoCRJju10hlM+nQ+LnNSSsiuehvLFdVyRqysq
        rbWX3vStx1AG12++LT5FNLyaeQKBgQDDTn1gyjuJdXs9TafsFfWEYS71FysunOYn
        nsnF4C5SLPg2paC2xU+Lby2UMYv++7QuS8xkqgr7+qMNniWo0I6EV5T1HKLtNgBf
        ies86I2FH3Fl8dEy/PyaX5X7G1DtwFZHEx6+U9LNx7v25gRQqg3keml7PlwaLJtG
        iFfkQXr9OwKBgDoYXD4zUpykh+p/UdQwrEl3R9HqmOo4Kp6hxfpcPnuXBzRwp53r
        hX9Y36dSdzlOT+iU8gGbbflgBWuQREf/Fwlan96hiQdpq/p1ZOW9tBVnUdRUJVKL
        XiU0cNh3Y9KWjAAq4n1XG+LdFGTQAz5nyNgENGgN3FTDp4pEh7DTeWGJAoGAWpFw
        VM0TNNg08SWsxC8erme+tcsrrC74D9Fzsf4WnObbp8PAtmDjVT6WPU2IpRKl6H4f
        52JvO5Brwmne/tzP6hEPM2c3KpdLLwKvAoy468278VFk+KcWoKPI0ixFqCr0F3uH
        Wy1V6TVBNepOf/WMAbK+bXdqkHy0+M1LLL8swHcCgYEAxG766jD/Y1rXmRp3/P5w
        qxvQCcSssF9Nk6AUvsYV6EdiSnlEG/ZS49fDpugeadMYAzzetL9TLyjL44lZxq1w
        7pxFizS8W9uQgm8a91nzdkmMx24Rsw7eZqPYZYhcFGv/fr6QwH5h3MbM1kdI3oev
        BbqNbATttAvO/XFz5kNeUr0=
        -----END PRIVATE KEY-----
        """
        ).encode(),
    )
    token = "unittest-token"
    routes = web.RouteTableDef()
    cluster_response_iter = iter(cluster_responses)

    @routes.post("/container-infra/v1/clusters")
    async def create_magnum_cluster(request):
        cluster = await request.json()

        if "node_count" in cluster:
            assert cluster["node_count"] is not None
        else:
            cluster["node_count"] = 3

        if "master_count" in cluster:
            assert cluster["master_count"] is not None
        else:
            cluster["master_count"] = 1

        cluster["uuid"] = fake.uuid4()
        request.app["clusters"][cluster["uuid"]] = cluster

        return web.json_response({"uuid": cluster["uuid"]}, status=202)

    @routes.get("/container-infra/v1/clusters/{ident}")
    async def read_magnum_cluster(request):
        cluster = request.app["clusters"].get(request.match_info["ident"])
        if cluster is None:
            raise web.HTTPNotFound()

        try:
            response = next(cluster_response_iter)
        except StopIteration as err:
            raise web.HTTPNotFound() from err

        return web.json_response(dict(cluster, **response))

    @routes.delete("/container-infra/v1/clusters/{ident}")
    async def delete_magnum_cluster(request):
        cluster = request.app["clusters"].get(request.match_info["ident"])
        if cluster is None:
            raise web.HTTPNotFound()

        return web.json_response({"uuid": cluster["uuid"]})

    @routes.post("/container-infra/v1/clusters/{ident}/actions/resize")
    async def resize_magnum_cluster(request):
        cluster = request.app["clusters"].get(request.match_info["ident"])
        if cluster is None:
            raise web.HTTPNotFound()

        body = await request.json()
        cluster["node_count"] = body["node_count"]

        return web.json_response({"uuid": cluster["uuid"]})

    @routes.get("/container-infra/v1/certificates/{ident}")
    async def read_certificate(request):
        cluster = request.app["clusters"].get(request.match_info["ident"])
        if cluster is None:
            raise web.HTTPNotFound()

        return web.json_response(
            {
                "uuid": cluster["uuid"],
                "pem": crypto.dump_certificate(crypto.FILETYPE_PEM, ca).decode(),
            }
        )

    @routes.post("/container-infra/v1/certificates")
    async def create_certificate(request):
        body = await request.json()
        cluster = request.app["clusters"].get(body["cluster_uuid"])
        if cluster is None:
            raise web.HTTPNotFound()

        csr = crypto.load_certificate_request(crypto.FILETYPE_PEM, body["csr"])

        cert = crypto.X509()
        cert.set_issuer(ca.get_subject())
        cert.set_subject(csr.get_subject())
        cert.set_pubkey(csr.get_pubkey())
        cert.sign(ca_key, "sha256")

        return web.json_response(
            {
                "uuid": cluster["uuid"],
                "pem": crypto.dump_certificate(crypto.FILETYPE_PEM, cert).decode(),
            }
        )

    @routes.get("/container-infra/v1/clustertemplates/{ident}")
    async def create_cluster_template(request):
        template = request.app["cluster_templates"].get(request.match_info["ident"])
        if template is None:
            raise web.HTTPNotFound()

        return web.json_response(template)

    @routes.post("/identity/v3/auth/tokens")
    async def create_token(request):
        return web.json_response(
            {
                "token": {
                    "expires_at": "2099-01-01T00:00:00.000000Z",
                    "catalog": [
                        {
                            "endpoints": [
                                {
                                    "region_id": "eu1",
                                    "url": str(
                                        request.url.with_path("/container-infra/v1")
                                    ),
                                    "region": "eu1",
                                    "interface": "public",
                                    "id": "a9f41ae4edab46f2899bf8360b639d3c",
                                    "name": "public container-infra",
                                }
                            ],
                            "type": "container-infra",
                            "id": "6e2656ea3a724505ab3a8166c1bafa64",
                            "name": "magnum",
                        }
                    ],
                }
            },
            headers={"X-Subject-Token": token},
        )

    app = web.Application(logger=logging.getLogger(), middlewares=[error_log()])
    app.add_routes(routes)
    app["clusters"] = {}
    app["cluster_templates"] = {
        "b2339833-8916-454a-86bd-06b450f69210": {
            "insecure_registry": "-",
            "labels": {"cgroup_driver": "cgroupfs", "kube_tag": "v1.11.6"},
            "updated_at": "-",
            "floating_ip_enabled": True,
            "fixed_subnet": "-",
            "master_flavor_id": "M",
            "uuid": "b2339833-8916-454a-86bd-06b450f69210",
            "no_proxy": "-",
            "https_proxy": "-",
            "tls_disabled": False,
            "keypair_id": "unittest-keypair",
            "public": False,
            "http_proxy": "-",
            "docker_volume_size": "-",
            "server_type": "vm",
            "external_network_id": "shared-public-IPv4",
            "cluster_distro": "fedora-atomic",
            "image_id": "Fedora Atomic 27 x86_64",
            "volume_driver": "-",
            "registry_enabled": False,
            "docker_storage_driver": "-",
            "apiserver_port": "-",
            "name": "c116_ansible_template",
            "created_at": "2019-01-01T00:00:00+00:00",
            "network_driver": "flannel",
            "fixed_network": "-",
            "coe": "kubernetes",
            "flavor_id": "S",
            "master_lb_enabled": False,
            "dns_nameserver": "1.1.1.1",
            "hidden": "",
        }
    }

    return app


async def test_resource_reception(aiohttp_server, config, db, loop):
    # Pending and not scheduled
    pending = MagnumClusterFactory(status__state=MagnumClusterState.PENDING)

    # Pending and scheduled
    scheduled = MagnumClusterFactory(
        status__state=MagnumClusterState.PENDING, status__is_scheduled=True
    )
    # Running
    running = MagnumClusterFactory(status__state=MagnumClusterState.RUNNING)

    # Failed
    failed = MagnumClusterFactory(status__state=MagnumClusterState.FAILED)

    # Running and deleted without finalizers
    deleted = MagnumClusterFactory(
        status__state=MagnumClusterState.RUNNING,
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )

    # Running, not scheduled and deleted with finalizers
    deleted_with_finalizer = MagnumClusterFactory(
        status__state=MagnumClusterState.RUNNING,
        metadata__finalizers=["magnum_cluster_deletion"],
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )

    # Failed and deleted with finalizers
    deleted_and_failed_with_finalizer = MagnumClusterFactory(
        status__state=MagnumClusterState.FAILED,
        metadata__finalizers=["magnum_cluster_deletion"],
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
    )

    assert pending.status.project is None
    assert scheduled.status.project is not None

    await db.put(pending)
    await db.put(scheduled)
    await db.put(running)
    await db.put(failed)
    await db.put(deleted)
    await db.put(deleted_with_finalizer)
    await db.put(deleted_and_failed_with_finalizer)

    server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(server), loop=loop) as client:
        controller = MagnumClusterController(server_endpoint(server), worker_count=0)
        # Update the client, to be used by the background tasks
        await controller.prepare(client)  # need to be called explicitly
        await controller.reflector.list_resource()

    assert pending.metadata.uid not in controller.queue.dirty
    assert scheduled.metadata.uid in controller.queue.dirty
    assert failed.metadata.uid not in controller.queue.dirty
    assert deleted.metadata.uid not in controller.queue.dirty
    assert deleted_with_finalizer.metadata.uid in controller.queue.dirty
    assert deleted_and_failed_with_finalizer.metadata.uid in controller.queue.timers


async def test_magnum_cluster_create(aiohttp_server, config, db, loop):
    openstack_app = make_openstack_app(
        [
            {
                "api_address": None,
                "master_addresses": [],
                "status": "CREATE_IN_PROGRESS",
                "node_addresses": [],
                "status_reason": None,
                "stack_id": "16b64063-31ed-42a2-b029-41c7594d71df",
            },
            {
                "api_address": "https://185.128.119.132:6443",
                "master_addresses": ["185.128.119.132"],
                "status": "CREATE_COMPLETE",
                "node_addresses": ["185.128.118.210"],
                "status_reason": "Stack CREATE completed successfully",
                "stack_id": "16b64063-31ed-42a2-b029-41c7594d71df",
            },
        ]
    )
    openstack_server = await aiohttp_server(openstack_app)

    project = ProjectFactory(
        spec__url=f"{server_endpoint(openstack_server)}/identity/v3",
        spec__template="b2339833-8916-454a-86bd-06b450f69210",
    )
    cluster = MagnumClusterFactory(
        metadata__name="my-cluster",
        status__state=MagnumClusterState.PENDING,
        status__project=resource_ref(project),
        status__template="b2339833-8916-454a-86bd-06b450f69210",
        spec__master_count=None,
        spec__node_count=None,
    )
    await db.put(project)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.state == MagnumClusterState.RUNNING
    assert stored.metadata.finalizers[-1] == "magnum_cluster_deletion"

    # Validate payloads sent to Magnum API
    sent = openstack_app["clusters"][cluster.status.cluster_id]
    assert sent["name"].startswith("testing-my-cluster-")

    assert stored.status.cluster is not None
    kube = await db.get(
        Cluster,
        namespace=stored.status.cluster.namespace,
        name=stored.status.cluster.name,
    )
    assert kube is not None
    assert resource_ref(cluster) in kube.metadata.owners


async def test_magnum_cluster_create_counts_not_none(aiohttp_server, config, db, loop):
    """Ensure that when the count for the masters and the nodes are set in the Magnum
    cluster specifications, they are used instead of the defaults from the templates.
    """
    openstack_app = make_openstack_app(
        [
            {
                "api_address": None,
                "master_addresses": [],
                "status": "CREATE_IN_PROGRESS",
                "node_addresses": [],
                "status_reason": None,
                "stack_id": "16b64063-31ed-42a2-b029-41c7594d71df",
            },
            {
                "master_count": 3,
                "node_count": 5,
                "api_address": "https://185.128.119.132:6443",
                "master_addresses": ["185.128.119.132"],
                "status": "CREATE_COMPLETE",
                "node_addresses": ["185.128.118.210"],
                "status_reason": "Stack CREATE completed successfully",
                "stack_id": "16b64063-31ed-42a2-b029-41c7594d71df",
            },
        ]
    )
    openstack_server = await aiohttp_server(openstack_app)

    project = ProjectFactory(
        spec__url=f"{server_endpoint(openstack_server)}/identity/v3",
        spec__template="b2339833-8916-454a-86bd-06b450f69210",
    )
    cluster = MagnumClusterFactory(
        metadata__name="my-cluster",
        status__state=MagnumClusterState.PENDING,
        status__project=resource_ref(project),
        status__template="b2339833-8916-454a-86bd-06b450f69210",
        spec__master_count=3,
        spec__node_count=5,
    )
    await db.put(project)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.state == MagnumClusterState.RUNNING
    assert stored.metadata.finalizers[-1] == "magnum_cluster_deletion"
    assert stored.spec.master_count == 3
    assert stored.spec.node_count == 5
    assert stored.status.node_count == 5

    # Validate payloads sent to Magnum API
    sent = openstack_app["clusters"][cluster.status.cluster_id]
    assert sent["name"].startswith("testing-my-cluster-")

    assert stored.status.cluster is not None
    kube = await db.get(
        Cluster,
        namespace=stored.status.cluster.namespace,
        name=stored.status.cluster.name,
    )
    assert kube is not None
    assert resource_ref(cluster) in kube.metadata.owners


async def test_magnum_cluster_template_type(aiohttp_server, config, db, loop):
    openstack_app = make_openstack_app([])
    openstack_app["cluster_templates"] = {
        "e37e99f5-5418-4fad-997f-761207ff2e2e": {
            "updated_at": "-",
            "floating_ip_enabled": True,
            "uuid": "e37e99f5-5418-4fad-997f-761207ff2e2e",
            "tls_disabled": False,
            "keypair_id": "unittest-keypair",
            "public": False,
            "server_type": "vm",
            "external_network_id": "shared-public-IPv4",
            "image_id": "Fedora Atomic 27 x86_64",
            "registry_enabled": False,
            "name": "unittest-mesos-template",
            "created_at": "2019-01-01T00:00:00+00:00",
            "coe": "mesos",
            "flavor_id": "S",
        }
    }
    openstack_server = await aiohttp_server(openstack_app)

    project = ProjectFactory(
        spec__url=f"{server_endpoint(openstack_server)}/identity/v3",
        spec__template="e37e99f5-5418-4fad-997f-761207ff2e2e",
    )
    cluster = MagnumClusterFactory(
        status__state=MagnumClusterState.PENDING,
        status__project=resource_ref(project),
        status__template="e37e99f5-5418-4fad-997f-761207ff2e2e",
    )
    assert cluster.status.cluster_id is None

    await db.put(project)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.state == MagnumClusterState.FAILED
    assert stored.status.cluster_id is None
    assert stored.status.reason.code == ReasonCode.INVALID_CLUSTER_TEMPLATE


async def test_handle_404_on_magnum_cluster_create(aiohttp_server, config, db, loop):
    openstack_app = make_openstack_app(
        [
            {
                "api_address": None,
                "master_addresses": [],
                "status": "CREATE_IN_PROGRESS",
                "node_addresses": [],
                "status_reason": None,
                "stack_id": "71622aef-a414-40aa-96c7-de6dfaed698b",
            }
        ]
    )
    openstack_server = await aiohttp_server(openstack_app)

    project = ProjectFactory(
        spec__url=f"{server_endpoint(openstack_server)}/identity/v3"
    )
    cluster = MagnumClusterFactory(
        metadata__name="my-cluster",
        status__state=MagnumClusterState.CREATING,
        status__project=resource_ref(project),
        spec__master_count=None,
        spec__node_count=None,
    )
    assert cluster.status.cluster_id is not None

    openstack_app["clusters"][cluster.status.cluster_id] = None

    await db.put(project)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )

    assert stored.status.state == MagnumClusterState.PENDING
    assert stored.status.cluster_id is None

    assert stored.status.cluster is not None
    kubernetes_cluster = await db.get(
        Cluster,
        namespace=stored.status.cluster.namespace,
        name=stored.status.cluster.name,
    )
    assert kubernetes_cluster is None


async def test_magnum_cluster_create_failed(aiohttp_server, config, db, loop):
    openstack_app = make_openstack_app(
        [
            {
                "api_address": None,
                "master_addresses": [],
                "status": "CREATE_IN_PROGRESS",
                "node_addresses": [],
                "status_reason": None,
                "stack_id": "71622aef-a414-40aa-96c7-de6dfaed698b",
            },
            {
                "api_address": None,
                "master_addresses": [],
                "status": "CREATE_FAILED",
                "status_reason": "Stack CREATE failed",
                "node_addresses": [],
                "stack_id": "71622aef-a414-40aa-96c7-de6dfaed698b",
            },
        ]
    )
    openstack_server = await aiohttp_server(openstack_app)

    project = ProjectFactory(
        spec__url=f"{server_endpoint(openstack_server)}/identity/v3"
    )
    cluster = MagnumClusterFactory(
        metadata__name="my-cluster",
        status__state=MagnumClusterState.CREATING,
        status__project=resource_ref(project),
        spec__master_count=None,
        spec__node_count=None,
    )
    assert cluster.status.cluster_id is not None

    openstack_app["clusters"][cluster.status.cluster_id] = {
        "uuid": cluster.status.cluster_id
    }

    await db.put(project)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.state == MagnumClusterState.FAILED
    assert stored.status.cluster_id is not None
    assert stored.status.reason.code == ReasonCode.CREATE_FAILED
    assert stored.status.reason.message == "Stack CREATE failed"

    assert stored.status.cluster is not None
    kubernetes_clusters = [c async for c in db.all(Cluster)]
    assert len(kubernetes_clusters) == 0


async def test_magnum_cluster_resize(aiohttp_server, config, db, loop):
    openstack_app = make_openstack_app(
        [
            {
                "master_count": 1,
                "node_count": 5,
                "api_address": "https://185.128.119.132:6443",
                "master_addresses": ["185.128.119.132"],
                "status": "UPDATE_IN_PROGRESS",
                "node_addresses": ["185.128.118.210"],
                "stack_id": "ff9e97a9-db1e-4fed-ac6f-b219c14846e7",
            },
            {
                "master_count": 1,
                "node_count": 5,
                "api_address": "https://185.128.119.132:6443",
                "master_addresses": ["185.128.119.132"],
                "status": "UPDATE_COMPLETE",
                "node_addresses": ["185.128.118.210"],
                "stack_id": "ff9e97a9-db1e-4fed-ac6f-b219c14846e7",
            },
        ]
    )
    openstack_server = await aiohttp_server(openstack_app)

    project = ProjectFactory(
        spec__url=f"{server_endpoint(openstack_server)}/identity/v3"
    )
    cluster = MagnumClusterFactory(
        metadata__name="my-cluster",
        status__state=MagnumClusterState.RUNNING,
        status__project=resource_ref(project),
        status__node_count=3,
        status__api_address="https://185.128.119.132:6443",
        status__master_addresses=["185.128.119.132"],
        status__node_addresses=["185.128.118.210"],
        spec__master_count=1,
        spec__node_count=5,
    )
    assert cluster.status.cluster_id is not None

    openstack_app["clusters"][cluster.status.cluster_id] = {
        "uuid": cluster.status.cluster_id,
        "node_count": cluster.status.node_count,
    }

    await db.put(project)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.state == MagnumClusterState.RUNNING
    assert stored.status.node_count == 5


async def test_magnum_cluster_update_failed(aiohttp_server, config, db, loop):
    """Ensures that a failed update is handled by the workers."""
    openstack_app = make_openstack_app(
        [
            {
                "master_count": 1,
                "node_count": 3,
                "api_address": "https://185.128.119.132:6443",
                "master_addresses": ["185.128.119.132"],
                "status": "UPDATE_IN_PROGRESS",
                "node_addresses": ["185.128.118.210"],
                "stack_id": "ff9e97a9-db1e-4fed-ac6f-b219c14846e7",
            },
            {
                "master_count": 1,
                "node_count": 3,
                "api_address": "https://185.128.119.132:6443",
                "master_addresses": ["185.128.119.132"],
                "status": "UPDATE_FAILED",
                "status_reason": "Stack UPDATE failed",
                "node_addresses": ["185.128.118.210"],
                "stack_id": "ff9e97a9-db1e-4fed-ac6f-b219c14846e7",
            },
        ]
    )
    openstack_server = await aiohttp_server(openstack_app)

    project = ProjectFactory(
        spec__url=f"{server_endpoint(openstack_server)}/identity/v3"
    )
    cluster = MagnumClusterFactory(
        metadata__name="my-cluster",
        status__state=MagnumClusterState.RUNNING,
        status__project=resource_ref(project),
        status__node_count=3,
        status__api_address="https://185.128.119.132:6443",
        status__master_addresses=["185.128.119.132"],
        status__node_addresses=["185.128.118.210"],
        spec__master_count=1,
        spec__node_count=5,
    )
    assert cluster.status.cluster_id is not None

    openstack_app["clusters"][cluster.status.cluster_id] = {
        "uuid": cluster.status.cluster_id,
        "node_count": cluster.status.node_count,
    }

    await db.put(project)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.state == MagnumClusterState.FAILED
    assert stored.status.cluster_id is not None
    assert stored.status.reason.code == ReasonCode.RECONCILE_FAILED
    assert stored.status.reason.message == "Stack UPDATE failed"

    assert stored.spec.node_count == 5
    assert stored.status.node_count == 3


async def test_handle_404_on_magnum_cluster_resize(aiohttp_server, config, db, loop):
    openstack_app = make_openstack_app(
        [
            {
                "master_count": 1,
                "node_count": 5,
                "api_address": "https://185.128.119.132:6443",
                "master_addresses": ["185.128.119.132"],
                "status": "UPDATE_IN_PROGRESS",
                "node_addresses": ["185.128.118.210"],
                "stack_id": "086043c2-b16b-4f85-a565-e2e95a1b19d0",
            }
        ]
    )
    openstack_server = await aiohttp_server(openstack_app)

    project = ProjectFactory(
        spec__url=f"{server_endpoint(openstack_server)}/identity/v3"
    )
    cluster = MagnumClusterFactory(
        metadata__name="my-cluster",
        status__state=MagnumClusterState.RUNNING,
        status__project=resource_ref(project),
        status__node_count=3,
        status__api_address="https://185.128.119.132:6443",
        status__master_addresses=["185.128.119.132"],
        status__node_addresses=["185.128.118.210"],
        spec__master_count=1,
        spec__node_count=5,
    )
    kubernetes_cluster = KubernetesClusterFactory(
        metadata__owners=[resource_ref(cluster)],
        metadata__name=cluster.status.cluster.name,
        metadata__namespace=cluster.status.cluster.namespace,
    )
    assert cluster.status.cluster_id is not None
    assert cluster.status.cluster == resource_ref(kubernetes_cluster)

    openstack_app["clusters"][cluster.status.cluster_id] = {
        "uuid": cluster.status.cluster_id,
        "node_count": cluster.status.node_count,
    }

    await db.put(project)
    await db.put(cluster)
    await db.put(kubernetes_cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.state == MagnumClusterState.PENDING
    assert stored.status.cluster_id is None

    assert stored.status.cluster is not None
    kubernetes_cluster = await db.get(
        Cluster,
        namespace=stored.status.cluster.namespace,
        name=stored.status.cluster.name,
    )
    assert kubernetes_cluster is not None


async def test_magnum_cluster_delete(aiohttp_server, config, db, loop):
    openstack_app = make_openstack_app(
        [
            {
                "api_address": None,
                "master_addresses": [],
                "status": "DELETE_IN_PROGRESS",
                "node_addresses": [],
                "status_reason": None,
                "stack_id": "4941dc5e-9616-4729-abbd-9c6cf111bd85",
            }
        ]
    )
    openstack_server = await aiohttp_server(openstack_app)

    project = ProjectFactory(
        spec__url=f"{server_endpoint(openstack_server)}/identity/v3"
    )
    cluster = MagnumClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["magnum_cluster_deletion", "cascade_deletion"],
        status__state=MagnumClusterState.RUNNING,
        status__project=resource_ref(project),
        spec__master_count=None,
        spec__node_count=None,
    )

    openstack_app["clusters"][cluster.status.cluster_id] = {
        "uuid": cluster.status.cluster_id
    }

    await db.put(project)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.state == MagnumClusterState.DELETING
    assert stored.metadata.finalizers == ["cascade_deletion"]
    assert stored.status.cluster_id is not None
    assert stored.status.cluster is not None


@pytest.mark.slow
async def test_magnum_cluster_delete_update(aiohttp_server, config, db, loop):
    """During the deletion of a Magnum cluster, it is updated by the controller (mostly
    to set its DELETING state). The reflectors watch the update events of the cluster,
    but the controller should not handle again the cluster.

    This test ensures that this event is handled the right way: when the cluster is
    already deleted, simply return without handling the cluster.

    The workflow is as follow:
      0. Insert the cluster in a "to-be-deleted" state in the database
      1. Handle the deletion of the cluster
      2. Ensures that, during deletion, the cluster was updated, thus reenqueued
      3. Ensures that the reenqueued cluster is ignored by the controller

    Some sleeping time is added between the calls to `consume` along with a debounce
    with a value of 1 to be sure to get only one value.
    """
    openstack_app = make_openstack_app(
        [
            {
                "api_address": None,
                "master_addresses": [],
                "status": "DELETE_IN_PROGRESS",
                "node_addresses": [],
                "status_reason": None,
                "stack_id": "4941dc5e-9616-4729-abbd-9c6cf111bd85",
            }
        ]
    )
    openstack_server = await aiohttp_server(openstack_app)

    project = ProjectFactory(
        spec__url=f"{server_endpoint(openstack_server)}/identity/v3"
    )
    # 0. Insert the cluster in a "to-be-deleted" state in the database
    cluster = MagnumClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["magnum_cluster_deletion"],
        status__state=MagnumClusterState.RUNNING,
        status__project=resource_ref(project),
        spec__master_count=None,
        spec__node_count=None,
    )

    openstack_app["clusters"][cluster.status.cluster_id] = {
        "uuid": cluster.status.cluster_id
    }

    await db.put(project)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1, debounce=1
        )
        await controller.prepare(client)

        reflector_task = loop.create_task(controller.reflector())

        # 1. Handle the deletion of the cluster
        await controller.consume(run_once=True)

        # 2. Ensures that, during deletion, the cluster was updated, thus reenqueued
        await asyncio.sleep(2)  # wait for the reflector to see the resource update
        assert controller.queue.size() == 1

        # 3. Ensures that the reenqueued cluster is ignored by the controller
        # (as not present on the database anymore.)
        await controller.consume(run_once=True)
        await asyncio.sleep(2)
        assert controller.queue.size() == 0

        reflector_task.cancel()
        with suppress(asyncio.CancelledError):
            await reflector_task

    # Finally ensure that the cluster was deleted
    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored is None


async def test_magnum_cluster_delete_failed(aiohttp_server, config, db, loop):
    openstack_app = make_openstack_app(
        [
            {
                "api_address": None,
                "master_addresses": [],
                "status": "DELETE_IN_PROGRESS",
                "node_addresses": [],
                "status_reason": None,
                "stack_id": "4941dc5e-9616-4729-abbd-9c6cf111bd85",
            },
            {
                "api_address": None,
                "master_addresses": [],
                "status": "DELETE_FAILED",
                "status_reason": "Stack DELETE failed",
                "node_addresses": [],
                "stack_id": "4941dc5e-9616-4729-abbd-9c6cf111bd85",
            },
        ]
    )
    openstack_server = await aiohttp_server(openstack_app)

    project = ProjectFactory(
        spec__url=f"{server_endpoint(openstack_server)}/identity/v3"
    )
    cluster = MagnumClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["magnum_cluster_deletion"],
        status__state=MagnumClusterState.DELETING,
        status__project=resource_ref(project),
    )
    assert cluster.status.cluster_id is not None

    openstack_app["clusters"][cluster.status.cluster_id] = {}

    await db.put(project)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), worker_count=0, poll_interval=0.1
        )
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.state == MagnumClusterState.FAILED
    assert stored.status.reason.code == ReasonCode.DELETE_FAILED
    assert stored.status.reason.message == "Stack DELETE failed"
    assert stored.status.cluster_id is not None
    assert stored.status.cluster is not None


async def test_handle_magnum_client_exception(aiohttp_server, config, db, loop):
    project = ProjectFactory()
    cluster = MagnumClusterFactory(
        status__state=MagnumClusterState.PENDING, status__project=resource_ref(project)
    )

    await db.put(project)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(server_endpoint(api_server))

        controller.reconcile_magnum_cluster = MagicMock()
        error = magnumclient.exceptions.BadGateway(
            method="POST", url="http://localhost:9876/v3/something"
        )
        controller.reconcile_magnum_cluster.side_effect = error

        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.state == MagnumClusterState.FAILED
    assert stored.status.reason.code == ReasonCode.OPENSTACK_ERROR
    assert (
        stored.status.reason.message
        == "Bad Gateway (HTTP 502): POST http://localhost:9876/v3/something"
    )
    assert stored.status.cluster_id is None

    assert stored.status.cluster is None
    kubernetes_clusters = [c async for c in db.all(Cluster)]
    assert len(kubernetes_clusters) == 0


async def test_retry_delete(aiohttp_server, config, db, loop):
    """Test if the cluster deletion is retried on a Keystone exception during
    deletion.
    """

    # Number of expected authentication requests
    RETRIES = 3

    # Future to signal number of expected authentication retries reached
    stop = loop.create_future()

    routes = web.RouteTableDef()

    @routes.post("/identity/v3/auth/tokens")
    async def create_token(request):
        counter = request.app.get("token_counter", 0)
        if counter >= RETRIES and not stop.done():
            stop.set_result(None)
        request.app["token_counter"] = counter + 1
        raise web.HTTPUnauthorized()

    openstack_app = web.Application(
        logger=logging.getLogger(), middlewares=[error_log()]
    )
    openstack_app.add_routes(routes)
    openstack_server = await aiohttp_server(openstack_app)

    project = ProjectFactory(
        spec__url=f"{server_endpoint(openstack_server)}/identity/v3"
    )
    cluster = MagnumClusterFactory(
        metadata__deleted=fake.date_time(tzinfo=pytz.utc),
        metadata__finalizers=["magnum_cluster_deletion"],
        status__state=MagnumClusterState.RUNNING,
        status__project=resource_ref(project),
    )
    assert cluster.status.cluster is not None

    await db.put(project)
    await db.put(cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), poll_interval=0.05
        )
        # Execute controller
        await controller.prepare(client)
        runner = loop.create_task(controller.run())

        # Wait for expected number of retries
        await stop

        # Stop controller
        runner.cancel()
        with suppress(asyncio.CancelledError):
            await runner

    stored = await db.get(
        MagnumCluster, namespace=cluster.metadata.namespace, name=cluster.metadata.name
    )
    assert stored.status.state == MagnumClusterState.FAILED
    assert stored.status.reason.code == ReasonCode.OPENSTACK_ERROR

    message = (
        "Unauthorized (HTTP 401): "
        f"POST {server_endpoint(openstack_server)}/identity/v3/auth/tokens"
    )
    assert stored.status.reason.message == message
    assert stored.status.cluster_id is not None
    assert stored.status.cluster is not None


async def test_reconcile_kubeconfig(aiohttp_server, config, db, loop):
    openstack_app = make_openstack_app(
        [
            {
                "api_address": "https://127.0.0.3:7443",
                "master_addresses": ["127.0.0.3"],
                "status": "CREATE_COMPLETE",
                "node_addresses": ["185.128.118.210"],
                "status_reason": "Stack CREATE completed successfully",
                "stack_id": "16b64063-31ed-42a2-b029-41c7594d71df",
            }
        ]
    )
    openstack_server = await aiohttp_server(openstack_app)

    project = ProjectFactory(
        spec__url=f"{server_endpoint(openstack_server)}/identity/v3"
    )
    cluster = MagnumClusterFactory(
        status__state=MagnumClusterState.RUNNING,
        status__project=resource_ref(project),
        status__api_address="https://127.0.0.3:7443",
    )
    kubernetes_cluster = KubernetesClusterFactory(
        metadata__owners=[resource_ref(cluster)],
        metadata__name=cluster.status.cluster.name,
        metadata__namespace=cluster.status.cluster.namespace,
    )
    # Set cluster API address to match the API address of Magnum cluster
    kubeconfig = kubernetes_cluster.spec.kubeconfig
    kubeconfig["clusters"][0]["cluster"]["server"] = cluster.status.api_address
    assert cluster.status.cluster is not None

    openstack_app["clusters"][cluster.status.cluster_id] = {
        "uuid": cluster.status.cluster_id
    }

    await db.put(project)
    await db.put(cluster)
    await db.put(kubernetes_cluster)

    api_server = await aiohttp_server(create_app(config))

    async with Client(url=server_endpoint(api_server), loop=loop) as client:
        controller = MagnumClusterController(
            server_endpoint(api_server), poll_interval=0.05
        )
        # Execute controller
        await controller.prepare(client)
        await controller.process_cluster(cluster)

    stored = await db.get(
        Cluster,
        namespace=cluster.status.cluster.namespace,
        name=cluster.status.cluster.name,
    )
    assert kubernetes_cluster.spec.kubeconfig != stored.spec.kubeconfig
