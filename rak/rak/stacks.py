#!/usr/bin/env python3

from heatclient.client import Client as Heat_Client
from keystoneclient.v3 import Client as Keystone_Client

import os

from time import sleep

STACK_DIR = "stacks"

# heat_client = None


def make_heat_client():
    def get_keystone_creds():
        creds = {}
        creds["username"] = os.environ["OS_USERNAME"]
        creds["password"] = os.environ["OS_PASSWORD"]
        creds["auth_url"] = os.environ["OS_AUTH_URL"]
        creds["project_name"] = os.environ["OS_PROJECT_NAME"]
        return creds

    print(os.environ["OS_AUTH_URL"])

    creds = get_keystone_creds()
    ks_client = Keystone_Client(**creds)
    heat_endpoint = ks_client.service_catalog.url_for(
        service_type="orchestration", endpoint_type="publicURL"
    )
    heat_client = Heat_Client("1", heat_endpoint, token=ks_client.auth_token)

    return heat_client


class StackNotFound(Exception):
    """Raised when a Stack is not found"""

    pass


class StackTimedOut(Exception):
    """Raised when all retries have failed for creating or updating a Stack"""

    pass


class StackFailed(Exception):
    """Raised if the stack goes to a fail state"""

    pass


def create_or_update_stack(
    heat_client,
    stack_name,
    stack_filename,
    parameters=None,
    wait=False,
    retry=10,
    interval=1,
):
    """Create a Heat stack with the given stack name if it doesn't already
    exist. Update the existing stack otherwise.

    Args:
        heat_client (heatclient.client.Client): Heat Client
        stack_name (str): Name of the Heat stack
        stack_filename (str): Path to the Heat template
        parameters (dict, optional): Heat template parameters
        wait (bool, optional): Controls if we should block and wait for the
            Heat stack to be created / updated
        retry (int, optional): Maximum number of retries before  raising a
            timeout error. Ignored if wait=False
        interval (int, optional): Amount of seconds to wait between retries.
            Ignored if wait=False

    Returns:
        heatclient.v1.stacks.Stack: the created or updated Heat stack

    Raises:

        StackTimedOut: if wait=True and the creation/update of the Heat stack
            is still in progress after the maximum number of retries as been
            reached.
        StackFailed: if wait=True and the Stack goes into failed state.
    """
    try:
        stack = get_stack_by_name(heat_client, stack_name)
    except StackNotFound:
        print("Creating Stack")
        stack = create_stack(heat_client, stack_name, stack_filename, parameters)
    else:
        print("Stack already exists, updating")
        update_stack(heat_client, stack, stack_filename, parameters)

    stack = get_stack_by_name(heat_client, stack_name)
    print(stack)

    if not wait:
        return stack

    print("Waiting for Stack to be completed")
    stack_status = get_stack_status(heat_client, stack.id)
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
        stack_status = get_stack_status(heat_client, stack.id)

    return stack


def get_stack_status(heat_client, stack_id):
    """Returns the Heat stack status

    The current status has to be polled from the OpenStack Heat endpoint.
    Possible values for the Heat stack status are:
    - CREATE_IN_PROGRESS
    - CREATE_COMPLETE
    - CREATE_FAILED
    - UPDATE_IN_PROGRESS
    - UPDATE_COMPLETE
    - UPDATE_FAILED
    - DELETE_IN_PROGRESS
    - DELETE_COMPLETE
    - DELETE_FAILED

    Args:
        stack_id (uuid): The OpenStack UUID of the Heat stack to check

    Returns:
        string: The status of the Heat Stack

    """
    stack = heat_client.stacks.get(stack_id)
    return stack.stack_status


def create_stack(heat_client, stack_name, stack_file_path, parameters=None):
    """Create a new Heat Stack

    Args:
        stack_name (str): The name of the Heat stack to create. This is also a
            unique identifier for Heat stacks
        stack_filename (str): Path to the Heat template
        parameters (dict, optional): Heat template parameters

    """

    #    current_dir = os.path.dirname(os.path.realpath(__file__))
    # stack_file_path = os.path.join(current_dir, STACK_DIR, f"{stack_filename}.yml")
    #    stack_file_path = os.path.join(current_dir, STACK_DIR, f"{stack_filename}.yml")

    template = open(f"{stack_file_path}.yml")
    if parameters:
        heat_client.stacks.create(
            stack_name=stack_name, template=template.read(), parameters=parameters
        )
    else:
        heat_client.stacks.create(stack_name=stack_name, template=template.read())
    template.close()


def update_stack(heat_client, stack, stack_filename, parameters=None):
    """Update an existing Heat Stack

    Args:
        stack_name (str): The name of the Heat stack to create. This is also a
            unique identifier for Heat stacks
        stack_filename (str): Path to the Heat template
        parameters (dict, optional): Heat template parameters
    """
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


def delete_stack_by_name(
    heat_client, stack_name, wait=False, retry=10, interval=1, allow_notfound=False
):
    """Create a Heat Stack

    Args:

        stack_name (str): The name of the Heat stack to create. This is also a
            unique identifier for Heat stacks
        wait (bool, optional): Controls if we should wait for the Heat Stack
            to be deleted before returning.
        retry (int, optional): Maximum number of retries before  raising a
            timeout error. Ignored if wait=False
        interval (int, optional): Amount of seconds to wait between retries.
            Ignored if wait=False
        allow_notfound (bool, optional): Controls if we should raise an
            Exception if the stack is not present

    Returns:
        heatclient.v1.stacks.Stack: the created Heat stack
    """

    try:
        stack = get_stack_by_name(heat_client, stack_name)
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
            get_stack_by_name(heat_client, stack.stack_name)
        except StackNotFound:
            print("Finally gone")
            return
        else:
            print("Stack is till there")
            sleep(1)


def list_stacks(heat_client):
    """List Heat Stack

    Returns:
        list: List of Heat Stack objects
    """
    return heat_client.stacks.list()


def get_stack_by_name(heat_client, stack_name):
    """Look for a stack using the stack name.

    The Heat client doesn't allow looking for a stack by name, only by UUID.
    Stack names are unique in OpenStack Heat, so we need to have a way to look
    for a stack by name.

    Args:
        stack_name (str): The name of the Stack

    Returns:
        heatclient.v1.stacks.Stack: the Heat stack object, if found

    Raises:
        StackNotFound: if the Heat stack doesn't exist.
    """

    for stack in list_stacks(heat_client):
        if stack.stack_name == stack_name:
            return stack

    raise StackNotFound


def get_stack_outputs(stack):
    """Get the output from a Heat Stack

    Args:
        stack (heatclient.v1.stacks.Stack): Stack to get output from.

    Returns:
        dict: A dictionary containing the stack outputs
    """

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
