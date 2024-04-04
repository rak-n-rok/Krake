from krake.api.app import create_app
from krake.api.helpers import HttpProblem, HttpProblemTitle
from krake.data.kubernetes import (
    Application,
    ApplicationState,
)

from tests.factories.kubernetes import (
    ApplicationFactory,
)
from tests.controller.kubernetes import deployment_manifest
from tests.controller.kubernetes.test_tosca import (
    create_tosca_from_resources,
    CSAR_META,
)
from tests.api.test_core import assert_valid_metadata


async def test_create_application(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory(status=None)

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=data.serialize()
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert_valid_metadata(received.metadata, "testing")
    assert received.spec == data.spec
    assert received.status.state == ApplicationState.PENDING

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_create_application_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.post("/kubernetes/namespaces/testing/applications")
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "create"):
        resp = await client.post("/kubernetes/namespaces/testing/applications")
        assert resp.status == 415


async def test_create_application_with_existing_name(aiohttp_client, config, db):
    existing = ApplicationFactory(metadata__name="existing")
    await db.put(existing)

    client = await aiohttp_client(create_app(config=config))

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=existing.serialize()
    )
    assert resp.status == 409

    received = await resp.json()
    problem = HttpProblem.deserialize(received)
    assert problem.title == HttpProblemTitle.RESOURCE_ALREADY_EXISTS


async def test_create_application_tosca_from_dict(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    tosca = create_tosca_from_resources([deployment_manifest])
    data = ApplicationFactory(
        status=None,
        spec__manifest=[],
        spec__tosca=tosca,
    )

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=data.serialize()
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert_valid_metadata(received.metadata, "testing")
    assert received.status.state == ApplicationState.PENDING
    assert received.spec == data.spec

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_create_application_tosca_from_url(
    aiohttp_client, config, db, file_server
):
    client = await aiohttp_client(create_app(config=config))

    tosca_url = file_server(create_tosca_from_resources([deployment_manifest]))
    data = ApplicationFactory(
        status=None,
        spec__manifest=[],
        spec__tosca=tosca_url,
    )

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=data.serialize()
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert_valid_metadata(received.metadata, "testing")
    assert received.status.state == ApplicationState.PENDING
    assert received.spec == data.spec

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received


async def test_create_application_csar_from_url(
    aiohttp_client, config, db, archive_files, file_server
):
    client = await aiohttp_client(create_app(config=config))

    tosca = create_tosca_from_resources([deployment_manifest])
    csar_path = archive_files(
        archive_name="archive.csar",
        files=[
            ("tosca.yaml", tosca),
            (
                "TOSCA-Metadata/TOSCA.meta",
                CSAR_META.format(entry_definition="tosca.yaml"),
            ),
        ],
    )
    csar_url = file_server(csar_path, file_name="example.csar")
    data = ApplicationFactory(
        status=None,
        spec__manifest=[],
        spec__csar=csar_url,
    )

    resp = await client.post(
        "/kubernetes/namespaces/testing/applications", json=data.serialize()
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())

    assert_valid_metadata(received.metadata, "testing")
    assert received.status.state == ApplicationState.PENDING
    assert received.spec == data.spec

    stored = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert stored == received
