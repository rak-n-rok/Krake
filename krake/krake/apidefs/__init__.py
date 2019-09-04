"""Declarative Krake API definitions. These definitions can be used to remove
a lot of boiler-plate code by providing standard implementations based in
these defintions for the API server and API client.
"""


_resources_collected = {}


def get_collected_resources():
    """Get the API resources that the Garbage Collector has to manage

    Returns:
        dict: a dictionary of the resources with the keys as the resource class
            and the value as corresponding API definitions that manage the key
            ("<data_class>: <API_definition>")

    """
    return _resources_collected


def garbage_collected(resource):
    """Decorator to add an API definition to the ones the Garbage Collector has
    to handle.

    Args:
        resource: the data resource which is managed by this API definition

    Returns:
        callable: decorator adding the current API definition class to the garbage
            collected classes

    """

    def decorator(cls):
        _resources_collected[resource] = cls
        return cls

    return decorator
