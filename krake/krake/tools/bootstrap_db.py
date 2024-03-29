#!/usr/bin/env python3

"""This script can be used to insert previously defined resource in the Krake database,
without having to start Krake components.

It can be used as follows:

.. code:: bash

    krake_bootstrap_db [OPTIONS] <file_1> <file_2> ... <file_n>

    # Or from stdin:
    my-program | krake_bootstrap_db - [OPTIONS]

The definition of the resources must be written in YAML files, with the following
structure:

 * several resources can be put in files, with separation ("---");
 * the API and kind need to be specified;
 * the object name needs to be specified in the metadata;
 * if not given, the UID, created and modified timestamp will be set automatically by
   the script;
 * the rest of the resource needs to follow the structure of the resource to insert,
   with attribute names as keys, and values as actual value of the attributes.

This example will insert two objects in the database:

    .. code:: yaml

        api: my-api
        kind: MyKind
        metadata:
          name: my-object
        attr_1: <specific-value>
        attr_2:
          attr_2_1:
          - <elt_1>
          - <elt_2>
          attr_2_2: <specific-value>
        ---

        api: my-api
        kind: MyOtherKind
        metadata:
          name: my-other-object
        attr: <value>

Every resource will be first validated before being inserted in the database.

A resource will not be inserted in the database if this resource already exists, even if
the content is different. This will be considered as an error. This behavior can be
overridden by using the ``--force`` argument. In this case, the resource present is
completely removed, and the newly defined one is added.

If any issue arises during insertion, the newly inserted values will be removed, and if
previous values were present and have been replaced, they will be added again. Issues
can happen in different cases:

 * a validation error if the resource could not be deserialized. That means the resource
   as written in the file has errors in it;
 * the resource already present in the database. This can only happen if the ``--force``
   argument is not used;
 * the API or kind of the resource is not supported by the script. In this case, either
   a typo is the cause, or the API and kind need to be added to the handled resources
   dictionary. This needs to be done with care.

The script needs Krake to be installed to be launched.
"""

import argparse
import asyncio
from krake import utils
import sys
from typing import NamedTuple
from uuid import uuid4

import yaml
from krake.api.database import Session
from krake.data.core import (
    Role,
    RoleBinding,
    GlobalMetric,
    GlobalMetricsProvider,
    Metric,
    MetricsProvider,
    resource_ref,
)
from krake.data.serializable import Serializable
from marshmallow import ValidationError


"""For each API, this stores the resources handled, with a
"<resource_class_name>: <resource_class>" match.
"""
_handled_resources = {
    "core": {
        "Role": Role,
        "RoleBinding": RoleBinding,
        "GlobalMetric": GlobalMetric,
        "GlobalMetricsProvider": GlobalMetricsProvider,
        "Metric": Metric,
        "MetricsProvider": MetricsProvider,
    }
}


class ResourcePresentException(BaseException):
    """Custom exception for the case of trying to insert a resource in the database
    which is already present.
    """

    def __init__(self):
        default_message = "Resource already present in database"
        super().__init__(default_message)


class InsertionResult(NamedTuple):
    """Keep the important elements of an attempt to insert a resource into the database.
    This is used in both cases: failure or success.

    Attributes:
        previous (Serializable): the resource that was stored in the database before
            attempting to add an updated value. None if no resource was present.
        to_insert (Serializable): the resource that was added to the database. None if
            no resource was actually added.
        error (BaseException): the error that occurred during pre-processing or during
            insertion. None if no error occurred.
        message (str): a message to display in case of errors. None if no error
            occurred.
    """

    previous: Serializable = None
    to_insert: Serializable = None
    error: BaseException = None
    message: str = None


def _create_identification_message(resource):
    """From a resource, attempt to get all information to identify it, in order to
    create a message that can be used to locate the resource for investigation.

    Args:
        resource (dict): the resource for which a message should be created.

    Returns:
        str: the message created for identification purposes.

    """
    kind = resource.get("kind", "MISSING")
    api = resource.get("api", "MISSING")

    metadata = resource.get("metadata")
    name = "MISSING"
    namespace = "MISSING"
    if metadata:
        name = metadata.get("name", "MISSING")
        namespace = metadata.get("namespace", "MISSING")

    return f"kind: {kind!r}, api: {api!r}, namespace: {namespace!r}, name: {name!r}"


async def insert_resource(resource, db_host, db_port, force=False):
    """Attempt to add the given resource to the database. If no UID, ``created`` or
    ``modified`` timestamp are defined, they will be set automatically.

    If not specified, a resource that is already present will prevent adding it again.
    Otherwise, the resource will be completely overwritten with the newly added one.

    Args:
        resource (dict): the dictionary that represents a resource to add.
        db_host (str): the host of the database to connect to.
        db_port (int): the port of the database to connect to.
        force (bool): if True, a resource already present in the database will be
            deleted and replaced by the given one. Otherwise, it is not added, and a
            ResourcePresentException is returned.

    Returns:
        InsertionResult: the summary of the attempt to insert. It can be used for
            logging and rollback purposes.

    """

    api = resource["api"]
    kind = resource["kind"]
    try:
        name_cls_mapping = _handled_resources[api]
    except KeyError as err:
        message = _create_identification_message(resource)
        error = ValueError(f"The api '{err.args[0]}' could not be found.")
        return InsertionResult(error=error, message=message)

    try:
        cls = name_cls_mapping[kind]
    except KeyError as err:
        message = _create_identification_message(resource)
        error = ValueError(f"The kind '{err.args[0]}' could not be found.")
        return InsertionResult(error=error, message=message)

    # Validation of the resource's structure.
    try:
        instance = cls.deserialize(resource, creation_ignored=True)
    except ValidationError as err:
        message = _create_identification_message(resource)
        return InsertionResult(error=err, message=message)

    async with Session(host=db_host, port=db_port) as session:
        kwargs = {"name": instance.metadata.name}
        if instance.metadata.namespace:
            kwargs["namespace"] = instance.metadata.namespace
        stored = await session.get(cls, **kwargs)

        to_store = instance
        if stored:
            # If the resource is present in the database
            if not force:
                # If it should not be replaced, quit
                return InsertionResult(
                    previous=stored,
                    error=ResourcePresentException(),
                    message=str(resource_ref(stored)),
                )

            await session.delete(stored)

        now = utils.now()
        if not to_store.metadata.uid:
            to_store.metadata.uid = str(uuid4())
        if not to_store.metadata.created:
            to_store.metadata.created = now
        if not to_store.metadata.modified:
            to_store.metadata.modified = now

        await session.put(to_store)

    print(f" * {resource_ref(to_store)}")
    return InsertionResult(previous=stored, to_insert=to_store)


async def insert_from_file(src_path, db_host, db_port, force=False):
    """Read the content of the given file and attempt to add each resource defined in
    it to the database.

    Args:
        src_path (_io.TextIOWrapper): file object to access the actual file to read.
        db_host (str): the host of the database to connect to.
        db_port (int): the port of the database to connect to.
        force (bool): if True, resources already present in the database will be deleted
            and replaced by the ones read from the file. Otherwise, they are not added.

    Returns:
        list: list of :class:`InsertionResult`. For each resource read from the file,
            an element is present in the list.

    """
    # Ensures that the file will be closed, even if an exception is raised.
    with src_path as src_path:
        resources = yaml.safe_load_all(src_path)

        result = await asyncio.gather(
            *(
                insert_resource(resource, db_host, db_port, force)
                for resource in resources
            )
        )
    return result


async def rollback(results, db_host, db_port):
    """Restore the database to state as it was prior to starting inserting the
    resources.

    If a resource was present and has been replaced, restore it to its previous state.
    If a resource was not present, remove it.

    Args:
        results (list): the list of list of :class:`InsertionResult` that were created
            after the attempts to insert resources to the database.
        db_host (str): the host of the database to connect to.
        db_port (int): the port of the database to connect to.

    Returns:
        list: a list of string, one element per line to be printed out as log for the
            rollback.

    """
    message = ["#############", "Rollback to previous state has been performed:"]
    async with Session(host=db_host, port=db_port) as session:
        for results_per_file in results:
            for result in results_per_file:
                # If result.to_insert is None, then nothing was added to the database,
                # nor removed.

                # If there was a resource before, and a new one replaced it,
                # roll it back to the previous version of it.
                if result.previous and result.to_insert:
                    await session.delete(result.to_insert)
                    await session.put(result.previous)
                    message.append(
                        f" * Resource {resource_ref(result.previous)} has been restored"
                        f" to previous state."
                    )

                # If there was no resource before, but adding a new one was added,
                # remove it.
                if not result.previous and result.to_insert:
                    await session.delete(result.to_insert)
                    message.append(
                        f" * Resource {resource_ref(result.to_insert)} added has been"
                        f" removed."
                    )
    return message


async def process_resources(src_files, db_host, db_port, force):
    """For each file path given, insert the resources defined in it to a database.

    Args:
        src_files (list[_io.TextIOWrapper]): the list of all files to read to get the
            resources, as list of file objects that are bound to the actual files.
        db_host (str): the host of the database in which the resources will be inserted.
        db_port (int): the port of the database in which the resources will be inserted.
        force (bool): if True, resources already present in the database will be deleted
            and replaced by the ones read from the files. Otherwise, they are not added.

    Returns:
        str: if an error occurred for at least a resource, a message is returned
            explaining the issue for each faulty resource.

    """
    print("Resources added to database:")

    # Return, for each file, the list of gathered result for inserting in the database.
    # The results is a list of list, with the latter storing "None" if no error occurred
    # for the resource, a tuple (resource, Exception) otherwise.
    # Example: with two files, "A.yaml" and "B.yaml", both with respective resources:
    # A_1, A_2 and B_1, B_2. If an error occurred for A_1 and B_2, the result will look
    # like (the ordering of read files and resources is kept):
    # assert result == [[(<A_1>, <exception>), None], [None, (<B_2>, <exception>)]]
    results = await asyncio.gather(
        *(
            insert_from_file(src_path, db_host, db_port, force)
            for src_path in src_files
        ),
        return_exceptions=False,
    )

    # If, for each file, no task returned an error, there was no error
    if not any(any(result.error for result in resources) for resources in results):
        return None

    # For each resource in each file for which inserting it led to an error,
    # print it along with its error.
    message = ["#############", "The following could not be added:"]
    for i, src_file in enumerate(src_files):
        message.append(f"In file {src_file.name!r}:")

        # results follows the same order for the resources as the one read.
        for insertion_result in results[i]:
            # If an error occurred during insertion of this resource:
            insertion_error = insertion_result.error
            if insertion_error:
                message.append(
                    f" * {insertion_result.message}, with error: {insertion_error!r}"
                )

    rollback_messages = await rollback(results, db_host, db_port)
    message.extend(rollback_messages)

    return "\n".join(message)


def main(src_files, db_host, db_port, force):
    """Start the script as an asyncio coroutine.

    Returns:
        src_files (list[_io.TextIOWrapper]): the list of all files to read to get the
            resources, as list of file objects that are bound to the actual files.
        db_host (str): the host of the database in which the resources will be inserted.
        db_port (int): the port of the database in which the resources will be inserted.
        force (bool): if True, resources already present in the database will be deleted
            and replaced by the ones read from the files. Otherwise, they are not added.
        str: if error occurred in the coroutine, a message is returned. Otherwise,
            return None.

    """
    loop = asyncio.get_event_loop()
    try:
        result = loop.run_until_complete(
            process_resources(src_files, db_host, db_port, force)
        )
        return result
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()


def add_option(parser, name, help, short=None, default=None, action=None, **kwargs):
    """Define a new option that is accepted by the parser. One of default or action
    parameter has to be given.

    Args:
        parser (ArgumentParser): argument parser on which the new option will be added
        name (str): the name of the newly added option.
        help (str): what will be printed in the help. The default value, if given,
            will be printed along.
        default (Any, optional): the default value that will be given to the option.
        action (str, optional): the argparse action to apply.
        kwargs (dict, optional): additional options given to the parser.

    """
    if not default and not action:
        sys.exit(f"For option {name}, both default and action cannot be empty")

    option = name.replace("_", "-")

    if default:
        help = f"{help} Default: '{default}'"
        # Prevent "None" to be added as default value if no default value is wanted
        kwargs["default"] = default

    if short:
        parser.add_argument(short, option, action=action, help=help, **kwargs)
    else:
        parser.add_argument(option, action=action, help=help, **kwargs)


def cli():
    parser = argparse.ArgumentParser(
        description=(
            "Insert Krake resources into the database directly, without using the API."
        )
    )
    parser.add_argument(
        "src_files",
        nargs="+",
        type=argparse.FileType("r"),
        default=sys.stdin,
        help=(
            "List of YAML files to read the resources definitions from."
            " Use '-' to read from stdin"
        ),
    )

    add_option(
        parser,
        "--force",
        "Insert the resources in the database even if they are already present.",
        short="-f",
        action="store_true",
    )
    add_option(
        parser, "--db-host", "Host for the database endpoint.", default="localhost"
    )
    add_option(parser, "--db-port", "Port for the database endpoint.", default=2379)

    arguments = vars(parser.parse_args())
    sys.exit(main(**arguments))
