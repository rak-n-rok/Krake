#!/usr/bin/env python3

from heatclient.client import Client as Heat_Client
from keystoneclient.v3 import Client as Keystone_Client

import os

from time import sleep

STACK_DIR = "stacks"


def get_keystone_creds():
    creds = {}
    creds["username"] = os.environ["OS_USERNAME"]
    creds["password"] = os.environ["OS_PASSWORD"]
    creds["auth_url"] = os.environ["OS_AUTH_URL"]
    creds["project_name"] = os.environ["OS_PROJECT_NAME"]
    return creds


creds = get_keystone_creds()
ks_client = Keystone_Client(**creds)
heat_endpoint = ks_client.service_catalog.url_for(
    service_type="orchestration", endpoint_type="publicURL"
)
heat_client = Heat_Client("1", heat_endpoint, token=ks_client.auth_token)


class StackNotFound(Exception):
    """Raised when a Stack is not found"""

    pass


class StackTimedOut(Exception):
    """Raised when all retries have failed for creating or updating a Stack"""

    pass


class StackFailed(Exception):

    pass


def create_or_update_stack(
    stack_name, stack_filename, parameters=None, wait=False, retry=10, interval=1
):
    try:
        stack = get_stack_by_name(stack_name)
    except StackNotFound:
        print("Creating Stack")
        stack = create_stack(stack_name, stack_filename, parameters)
    else:
        print("Stack already exists, updating")
        update_stack(stack, stack_filename, parameters)

    print(stack)

    if not wait:
        return stack

    print("Waiting for Stack to be completed")
    stack_status = get_stack_status(stack)
    while stack_status != "CREATE_COMPLETE" and stack_status != "UPDATE_COMPLETE":
        print(f"Stack status is: {stack_status}")
        retry -= 1
        if retry < 0:
            print("Timeout")
            raise StackTimedOut
        if stack_status == "CREATE_FAILED" or stack_status == "UPDATE_FAILED":
            raise StackFailed
        print("Waiting... will retry...")
        sleep(interval)
        stack_status = get_stack_status(stack)

    return stack


def get_stack_status(stack_to_check):
    stack = heat_client.stacks.get(stack_to_check.id)
    return stack.stack_status


def create_stack(stack_name, stack_filename, parameters=None):
    current_dir = os.path.dirname(os.path.realpath(__file__))
    stack_file_path = os.path.join(current_dir, STACK_DIR, f"{stack_filename}.yml")

    template = open(stack_file_path)
    if parameters:
        # stack = heat_client.stacks.create(
        heat_client.stacks.create(
            stack_name=stack_name, template=template.read(), parameters=parameters
        )
    else:
        # stack = heat_client.stacks.create(
        heat_client.stacks.create(stack_name=stack_name, template=template.read())
    template.close()

    return get_stack_by_name(stack_name)


def update_stack(stack, stack_filename, parameters=None):
    current_dir = os.path.dirname(os.path.realpath(__file__))
    stack_file_path = os.path.join(current_dir, STACK_DIR, f"{stack_filename}.yml")

    template = open(stack_file_path)
    if parameters:
        heat_client.stacks.update(
            stack_id=stack.id, template=template.read(), parameters=parameters
        )
    else:
        heat_client.stacks.update(stack_id=stack.id, template=template.read())
    template.close()


def delete_stack_by_name(stackname, wait=False, allow_notfound=False):
    try:
        stack = get_stack_by_name(stackname)
    except StackNotFound:
        if not allow_notfound:
            raise
        return

    heat_client.stacks.delete(stack.id)

    if not wait:
        return

    # TODO: Implement retry limit
    while True:
        try:
            get_stack_by_name(stack.stack_name)
        except StackNotFound:
            print("Finally gone")
            return
        else:
            print("Stack is till there")
            sleep(1)


def list_stacks():
    return heat_client.stacks.list()


def get_stack_by_name(stack_name):
    for stack in list_stacks():
        if stack.stack_name == stack_name:
            return stack

    raise StackNotFound


def get_stack_outputs(stack):

    stack_outputs = {}

    output_list = stack.output_list()
    for output in output_list["outputs"]:
        output_key = output["output_key"]
        output_show = stack.output_show(output_key)
        output_value = output_show["output"]["output_value"]

        if output_value is not None:
            stack_outputs[output_key] = output_value

    print(stack_outputs)

    return stack_outputs
