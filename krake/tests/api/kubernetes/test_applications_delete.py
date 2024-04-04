from krake.api.app import create_app
from krake.data.core import resource_ref
from krake.data.kubernetes import (
    Application,
    ApplicationState,
)

from tests.factories.kubernetes import (
    ApplicationFactory,
)
from tests.factories.fake import fake


async def test_delete_application(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    data = ApplicationFactory()
    await db.put(data)

    resp = await client.delete(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}"
    )
    assert resp.status == 200
    received = Application.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert deleted.metadata.deleted is not None
    assert "cascade_deletion" in deleted.metadata.finalizers


async def test_delete_application_rbac(rbac_allow, config, aiohttp_client):
    config.authorization = "RBAC"
    client = await aiohttp_client(create_app(config=config))

    resp = await client.delete(
        "/kubernetes/namespaces/testing/applications/my-resource"
    )
    assert resp.status == 403

    async with rbac_allow("kubernetes", "applications", "delete"):
        resp = await client.delete(
            "/kubernetes/namespaces/testing/applications/my-resource"
        )
        assert resp.status == 404


async def test_delete_application_already_in_deletion(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))

    in_deletion = ApplicationFactory(metadata__deleted=fake.date_time())
    await db.put(in_deletion)

    resp = await client.delete(
        f"/kubernetes/namespaces/testing/applications/{in_deletion.metadata.name}"
    )
    assert resp.status == 200


async def test_force_delete_application(aiohttp_client, config, db):
    client = await aiohttp_client(create_app(config=config))
    data = ApplicationFactory(status__state=ApplicationState.FAILED)
    await db.put(data)

    resp = await client.delete(
        f"/kubernetes/namespaces/testing/applications/{data.metadata.name}?force=True"
    )

    assert resp.status == 200

    received = Application.deserialize(await resp.json())
    assert resource_ref(received) == resource_ref(data)
    assert received.metadata.deleted is not None

    deleted = await db.get(Application, namespace="testing", name=data.metadata.name)
    assert deleted is None
