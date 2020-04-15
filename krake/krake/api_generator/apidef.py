"""This specific module handles the generation of an API definition, from the Krake API
provided. This Krake API is the Python path to its Krake data module.

The generator prints a file content. This should be put into a Python file, which can
then be integrated into Krake, in the ``krake.api.apidefs`` package.

The following syntax should be used:

.. code:: bash

    python -m krake.api_generator apidef <module_path> [<other_opts>...] > <module.path>

For example:

.. code:: bash

    python -m krake.api_generator apidef krake.data.core

"""
import sys
from functools import partial

import inspect

from krake.api_generator.utils import (
    add_templates_dir,
    add_template_path,
    StoreDict,
    get_data_classes,
    render_and_print,
    add_no_black_formatting,
)
from typing import NamedTuple, List

from krake.apidefs.definitions import Scope
from krake.data.serializable import ApiObject


default_scope = Scope.NAMESPACED

default_apidef_template = "apidef.jinja"


class ResourceDef(NamedTuple):
    """Represent the API definition of a Krake resource, as it will be added to the
    template. This definition is the class that contains all the Operations for a
    resource.

    Args:
        name (str): name of the resource definition class.
        scope (Scope): scope of the Krake resource.
        singular (str): name of the Krake resource, in singular.
        plural (str): name of the Krake resource, in plural.
        url_path (str): base URL endpoint for the Operations of the resource.
        res (type): reference to the class defined.
        res_list_name (str): name of the list pendant of the resource. To be used with
            "list" endpoints.
        subresources (list[str]): list of the name of the subresources of the class
            defined.

    """

    name: str
    scope: Scope
    singular: str
    plural: str
    url_path: str
    res: ApiObject
    res_list_name: str
    subresources: List[str] = None

    @property
    def namespaced(self):
        """Compute if a resource is namespaced or not.

        Returns:
            bool: True if the resource is namespaced, False otherwise.

        """
        return self.scope == Scope.NAMESPACED

    @classmethod
    def from_resource(
        cls, api_name, scope, data_class, name=None, plural=None, res_list_name=None
    ):
        """Create a :class:`ResourceDef` from a resource and its API name.

        Args:
            api_name (str): name of the API to which the resource belongs
            scope (Scope): scope of the resource.
            data_class (type): reference to the resource class.
            name (str, optional): name that will be given to the :class:`ResourceDef`.
                If not specified, the suffix "Resource" will be added.
            plural (str, optional): plural of the resource name. If not specified, an
                "s" character will be added.
            res_list_name (str, optional): name of the class that stores a list of the
                current resource. If not specified, the suffix "List" will be added.

        Returns:
            ResourceDef: the generated resource definition.

        """
        if not name:
            name = f"{data_class.kind}Resource"
        if not res_list_name:
            res_list_name = f"{data_class.kind}List"

        singular = data_class.kind
        if not plural:
            plural = f"{singular}s"

        if scope == Scope.NAMESPACED:
            url_path = f"/{api_name.lower()}/namespaces/{{namespace}}/{plural.lower()}"
        else:
            url_path = f"/{api_name.lower()}/{plural.lower()}"

        subresources = data_class.subresources_fields()

        return cls(
            name=name,
            scope=scope,
            singular=singular,
            plural=plural,
            url_path=url_path,
            res=data_class,
            res_list_name=res_list_name,
            subresources=subresources,
        )


def is_persistent_class(obj):
    """Check if an object is a class that is persisted in the Krake database.

    Args:
        obj: the given object to check.

    Returns:
        bool: True if the object given is a class persisted in the Krake database, False
            otherwise

    """
    return inspect.isclass(obj) and hasattr(obj, "__etcd_key__")


class Api(NamedTuple):
    """Represent an API object that will be put into the template.

    Args:
        name (str): name of the API in Krake.
        module_path (str): Python path to the module where the API data structures are
            defined. The syntax should be the module hierarchy separated with dots, for
            example: "krake.data.my_api".
        import_classes (list[str]): all classes that need to be imported by the final
            API definition.
        resources (list[ResourceDef]): the list of resource definitions that the final
            API definition should contain.

    """

    name: str
    module_path: str
    import_classes: List[str] = None
    resources: List[ResourceDef] = None

    @classmethod
    def create_resource_definitions(cls, api_name, data_classes, scopes):
        """For each persisted class in the API, create a corresponding
        :class:`ResourceDef` instance.

        Args:
            api_name (str): the name of the API
            data_classes (list[type]): the list of classes defined in the API.
            scopes (dict): the dictionary of scopes for each class defined in the API.
                The structure should be: "<resource_kind>: <resource_scope>". The kind
                is the one defined in the API (as a string), while the scope is an
                instance of :class:`Scope`. If a class is not present in the dictionary,
                the default one will be used.

        Returns:
            list[ResourceDef]: the list of created :class:`ResourceDef`.

        """
        result = []
        for data_class in data_classes:
            scope = scopes.get(data_class.kind, default_scope)
            resource_def = ResourceDef.from_resource(
                api_name, data_class=data_class, scope=scope
            )
            result.append(resource_def)
        return result

    @classmethod
    def create_import_classes(cls, resource_definitions):
        """Create the list of classes that need to be imported for the API definition
        from the resources definitions.

        Args:
            resource_definitions (list[ResourceDef]): a list of :class:`ResourceDef`.

        Returns:
            list[str]: the list of the name of the classes extracted from the resource
                definitions.

        """
        result = []
        for definition in resource_definitions:
            result.append(definition.singular)
            result.append(definition.res_list_name)

        return result

    @classmethod
    def from_path(cls, module_path, name=None, scopes=None):
        """Create an instance of :class:`Api` from the data structures of a Krake API.

        Args:
            module_path (str): The Python module path to the data structures. For
                example: "krake.data.my_api".
            name (str, optional): the name of the API.
            scopes (dict, optional): the dictionary of scopes for each class defined in
                the API. The structure should be: "<resource_kind>: <resource_scope>".
                The kind is the one defined in the API (as a string), while the scope is
                an instance of :class:`Scope`. If a class is not present in the
                dictionary, the default one will be used.

        Returns:
            Api: the api definition created.

        """
        if not name:
            name = module_path.split(".")[-1]

        # Get all ApiObject classes for which a resource definition will be created.
        data_classes = get_data_classes(module_path, condition=is_persistent_class)

        if not scopes:
            scopes = {}
        process_classes_scopes(scopes, data_classes)

        # Create a resource definition from each ApiObject class
        resource_definitions = cls.create_resource_definitions(
            name, data_classes, scopes=scopes
        )

        import_classes = cls.create_import_classes(resource_definitions)

        return cls(
            module_path=module_path,
            name=name,
            import_classes=import_classes,
            resources=resource_definitions,
        )


def process_classes_scopes(scopes, data_classes):
    """Parse all provided scopes to check the given class and scope values.

    Args:
        scopes (dict): a dictionary of the scope for each class, with the key-value
            pairs being: "<class_name>: <scope_as_string>". For example:
            "MyClass": "NAMESPACED".
        data_classes(list): a list of Krake data classes, to check against the given
            classes

    Raises:
        SystemExit: if the class name given does not exist, or if the scope given does
            not exist.

    """
    for name, scope in scopes.items():
        if name not in [e.kind for e in data_classes]:
            sys.exit(f"ERROR: The class {name!r} is not present in the given API")
        try:
            scopes[name] = Scope[scope]
        except KeyError:
            choices = [scope.name for scope in Scope]
            sys.exit(
                f"ERROR: Scope {scope!r} could not be found. Choose from: {choices}"
            )


def generate_apidef(data_path, templates_dir, template_path, no_black, scopes=None):
    """From a given Krake API module path, print an API definition file that contains
    the definition of all resources described in the API.

    Args:
        data_path (str): The Python module path to the data structures. For example:
            "krake.data.my_api".
        templates_dir (str): path of the directory in which the template is stored.
        template_path (str): name of the template.
        no_black (bool): if True, the black formatting will not be used.
        scopes (dict, optional): a dictionary of the scope for each class, with the
            key-value pairs being: "<class_name>: <scope_as_string>". For example:
            "MyClass": "NAMESPACED". If no value is provided, the default scope will be
            used for all classes.

    """
    if scopes is None:
        scopes = {}

    api_def = Api.from_path(data_path, scopes=scopes)

    parameters = {"api_def": api_def}
    render_and_print(templates_dir, template_path, parameters, no_black=no_black)


def add_apidef_subparser(subparsers):
    """Add the subparser that is specific for the generation of the API definition, as
    well as its arguments.

    Args:
        subparsers: the subparsers on which an additional parser should be added.

    """
    parser = subparsers.add_parser(
        "apidef",
        help="Generation of the API definitions, to be used as base for the Krake API.",
    )

    parser.add_argument(
        "data_path",
        help=(
            "Path to the module to parse for resource definitions. "
            "Syntax: '<path>.<to>.<module>'. Example: 'krake.data.foo'."
        ),
    )
    add_no_black_formatting(parser=parser)
    add_templates_dir(parser=parser)
    add_template_path(parser=parser, default=default_apidef_template)

    scope_choices = [scope.name for scope in Scope]
    parser.add_argument(
        "--scopes",
        action=partial(StoreDict, metavar="CLASS=SCOPE"),
        dest="scopes",
        help=(
            "Specify the scope that should be used for an individual class of the "
            "given module. To be specified for each different class. "
            f"Possible choices for a class are: {scope_choices}. "
            f"The default is {default_scope.name!r}."
        ),
    )

    parser.set_defaults(generator=generate_apidef)
