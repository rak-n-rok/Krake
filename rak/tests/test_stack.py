# import asyncio
import os

# import pytest

from aiohttp import web
from faker import Faker

from rak.stacks import (
    create_stack,
    make_heat_client,
    get_stack_by_name,
    update_stack,
    delete_stack,
    get_stack_outputs,
)

fake = Faker()


template_test = "template_test.yml"
current_dir = os.path.dirname(os.path.realpath(__file__))
template_path = os.path.join(current_dir, template_test)


def make_openstack_app(stack_responses):
    token = "unittest-token"
    routes = web.RouteTableDef()
    stack_responses_iter = iter(stack_responses)

    @routes.post("/orchestration/v1/{tenant_id}/stacks")
    async def create_heat_stack(request):
        stack = await request.json()

        stack["uuid"] = fake.uuid4()
        request.app["stacks"][stack["uuid"]] = stack

        response_body = {
            "stack": {
                "id": stack["uuid"],
                "links": [{"href": "someurl", "rel": "self"}],
            }
        }

        return web.json_response(response_body)  # 200

    @routes.get("/orchestration/v1/{tenant_id}/stacks/{ident}")
    async def find_stack(request):
        tenant_id = request.match_info["tenant_id"]
        ident = request.match_info["ident"]
        stack_name = request.app["stacks"].get(ident).get("stack_name")

        location = (
            f"{request.url.scheme}://{request.url.host}:{request.url.port}"
            f"/orchestration/v1/{tenant_id}/stacks/{stack_name}/{ident}"
        )

        response_body = {
            "code": "302 Found",
            "message": f'The resource was found at <a href="{location}">{location}'
            "</a>;\nyou should be redirected automatically.\n\n",
            "title": "Found",
        }

        return web.json_response(
            response_body, status=302, headers={"location": location}
        )

    @routes.get("/orchestration/v1/{tenant_id}/stacks/{stack_name}/{ident}")
    async def get_stack_details(request):
        stack = request.app["stacks"].get(request.match_info["ident"])

        # import pdb; pdb.set_trace()

        if stack is None:
            raise web.HTTPNotFound()

        try:
            response = next(stack_responses_iter)
        except StopIteration as err:
            raise web.HTTPNotFound() from err

        return web.json_response({"stack": dict(stack, **response)})

    @routes.get("/orchestration/v1/{tenant_id}/stacks")
    async def list_heat_stack(request):
        try:
            response = next(stack_responses_iter)
        except StopIteration as err:
            raise web.HTTPNotFound() from err

        stack_list = list(request.app["stacks"].values())
        stack_augmented_list = [{**s, **response} for s in stack_list]

        return web.json_response({"stacks": stack_augmented_list})

    @routes.put("/orchestration/v1/{tenant_id}/stacks/{stack_id}")
    async def update_heat_stack(request):
        stack = request.app["stacks"].get(request.match_info["stack_id"])

        stack_update = await request.json()

        print(stack)
        print(stack_update)

        request.app["stacks"][stack["uuid"]] = {**stack, **stack_update}

        response_body = {
            "code": "202 Accepted",
            "message": "The request is accepted for processing.<br /><br />\n\n\n",
            "title": "Accepted",
        }
        return web.json_response(response_body, status=202)

    @routes.delete("/orchestration/v1/{tenant_id}/stacks/{stack_name}/{stack_id}")
    async def delete_heat_stack(request):
        stack = request.app["stacks"].get(request.match_info["stack_id"])
        if stack is None:
            raise web.HTTPNotFound()

        return web.json_response(status=204)  # No Content

    @routes.delete("/orchestration/v1/{tenant_id}/stacks/{stack_id}")
    async def find_stack_for_delete(request):
        tenant_id = request.match_info["tenant_id"]
        ident = request.match_info["stack_id"]
        stack_name = request.app["stacks"].get(ident).get("stack_name")

        location = (
            f"{request.url.scheme}://{request.url.host}:{request.url.port}/"
            f"orchestration/v1/{tenant_id}/stacks/{stack_name}/{ident}"
        )

        response_body = {
            "code": "302 Found",
            "message": f'The resource was found at <a href="{location}">{location}'
            "</a>;\nyou should be redirected automatically.\n\n",
            "title": "Found",
        }

        return web.json_response(
            response_body, status=302, headers={"location": location}
        )

    @routes.post("/identity/v3/auth/tokens")
    async def create_token(request):
        resp = web.json_response(
            {
                "token": {
                    "expires_at": "2099-01-01T00:00:00.000000Z",
                    "catalog": [
                        {
                            "endpoints": [
                                {
                                    "region_id": "eu1",
                                    "url": str(
                                        request.url.with_path(
                                            "/orchestration/"
                                            "v1/a6944d763bf64ee6a275f1263fae0352"
                                        )
                                    ),
                                    "region": "eu1",
                                    "interface": "public",
                                    "id": "a9f41ae4edab46f2899bf8360b639d3c",
                                    "name": "public orchestration",
                                }
                            ],
                            "type": "orchestration",
                            "id": "6e2656ea3a724505ab3a8166c1bafa64",
                            "name": "heat",
                        }
                    ],
                    "is_domain": "false",
                    "issued_at": "2020-11-07T01:58:43.578929Z",
                    "methods": ["password"],
                    "project": {
                        "domain": {"id": "default", "name": "Default"},
                        "id": "a6944d763bf64ee6a275f1263fae0352",
                        "name": "MyProject",
                    },
                    "roles": [
                        {"id": "51cc68287d524c759f47c811e6463340", "name": "admin"}
                    ],
                    "user": {
                        "domain": {"id": "default", "name": "Default"},
                        "id": "ee4dfb6e5540447cb3741905149d9b6e",
                        "name": "MyUser",
                        "password_expires_at": "2020-11-06T15:32:17.000000",
                    },
                }
            },
            headers={"X-Subject-Token": token},
        )

        return resp

    # app = web.Application(logger=logging.getLogger(), middlewares=[error_log()])
    app = web.Application()
    app.add_routes(routes)
    app["stacks"] = {}

    return app


def test_create_stack(subprocess_server):
    openstack_app = make_openstack_app([{"stack_status": "CREATE_IN_PROGRESS"}])

    openstack_server = subprocess_server(openstack_app)
    os.environ["OS_AUTH_URL"] = f"{openstack_server.endpoint}/identity/v3/"
    os.environ["OS_PASSWORD"] = "MyPassword"
    os.environ["OS_PROJECT_NAME"] = "MyProject"
    os.environ["OS_USERNAME"] = "MyUser"

    heat_client = make_heat_client()

    server_name = "krake_myenv_01"

    stack_parameters = {"flavor": "MyFlavor"}

    create_stack(heat_client, "krake_myenv_01", template_path, stack_parameters)

    get_stack = get_stack_by_name(heat_client, server_name)

    assert get_stack.stack_name == "krake_myenv_01"
    assert get_stack.stack_status == "CREATE_IN_PROGRESS"


def test_update_stack(subprocess_server):
    openstack_app = make_openstack_app([{"stack_status": "UPDATE_IN_PROGRESS"}])
    stack_name = "krake_myenv_01"
    stack_uuid = "a162c68d-f109-41be-8fc7-0b141896cbfa"

    existing_stack = {
        "stack_name": stack_name,
        "template": "my_template",
        "parameters": {"flavor": "MyFlavor"},
        "uuid": stack_uuid,
        "status": "CREATE_COMPLETE",
    }

    openstack_app["stacks"][stack_uuid] = existing_stack

    openstack_server = subprocess_server(openstack_app)
    os.environ["OS_AUTH_URL"] = f"{openstack_server.endpoint}/identity/v3/"
    os.environ["OS_PASSWORD"] = "MyPassword"
    os.environ["OS_PROJECT_NAME"] = "MyProject"
    os.environ["OS_USERNAME"] = "MyUser"

    heat_client = make_heat_client()

    stack_parameters = {"flavor": "MyNewFlavor"}

    update_stack(heat_client, stack_uuid, template_path, stack_parameters)

    get_stack = heat_client.stacks.get(stack_uuid)

    assert get_stack.stack_name == stack_name
    assert get_stack.parameters["flavor"] == "MyNewFlavor"
    assert get_stack.stack_status == "UPDATE_IN_PROGRESS"


def test_delete_stack(subprocess_server):
    openstack_app = make_openstack_app([{"stack_status": "DELETE_IN_PROGRESS"}])
    stack_name = "krake_myenv_01"
    stack_uuid = "a162c68d-f109-41be-8fc7-0b141896cbfa"

    existing_stack = {
        "stack_name": stack_name,
        "template": "my_template",
        "parameters": {"flavor": "MyFlavor"},
        "uuid": stack_uuid,
        "status": "CREATE_COMPLETE",
    }

    openstack_app["stacks"][stack_uuid] = existing_stack

    openstack_server = subprocess_server(openstack_app)
    os.environ["OS_AUTH_URL"] = f"{openstack_server.endpoint}/identity/v3/"
    os.environ["OS_PASSWORD"] = "MyPassword"
    os.environ["OS_PROJECT_NAME"] = "MyProject"
    os.environ["OS_USERNAME"] = "MyUser"

    heat_client = make_heat_client()

    delete_stack(heat_client, stack_uuid)

    get_stack = heat_client.stacks.get(stack_uuid)

    assert get_stack.stack_status == "DELETE_IN_PROGRESS"


def test_get_stack_outputs(subprocess_server):
    openstack_app = make_openstack_app([{"stack_status": "DELETE_IN_PROGRESS"}])
    stack_name = "krake_myenv_01"
    stack_uuid = "a162c68d-f109-41be-8fc7-0b141896cbfa"

    existing_stack = {
        "stack_name": stack_name,
        "template": "my_template",
        "parameters": {"flavor": "MyFlavor"},
        "uuid": stack_uuid,
        "status": "CREATE_COMPLETE",
        "outputs": [
            {
                "description": "Private IP of the server",
                "output_key": "private_ip",
                "output_value": "192.168.100.1",
            }
        ],
    }

    openstack_app["stacks"][stack_uuid] = existing_stack

    openstack_server = subprocess_server(openstack_app)
    os.environ["OS_AUTH_URL"] = f"{openstack_server.endpoint}/identity/v3/"
    os.environ["OS_PASSWORD"] = "MyPassword"
    os.environ["OS_PROJECT_NAME"] = "MyProject"
    os.environ["OS_USERNAME"] = "MyUser"

    heat_client = make_heat_client()

    # stack = heat_client.stacks.get(stack_uuid, resolve_outputs=True)
    stack = get_stack_by_name(heat_client, stack_name)

    print(stack)

    stack_outputs = get_stack_outputs(stack)

    assert "private_ip" in stack_outputs
    assert stack_outputs["private_ip"] == "192.168.100.1"
