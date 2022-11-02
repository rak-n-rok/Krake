"""This module comprises TOSCA parser and translator."""
import logging

import yaml
from toscaparser.tosca_template import ToscaTemplate, log

from toscaparser.functions import GetInput, get_function, is_function, GetProperty
from toscaparser.functions import Concat
from toscaparser.common.exception import TOSCAException, ValidationError

# Set `toscaparser` logger to the WARNING level.
# The default INFO level does not log any important logs so far.
log.setLevel(logging.WARNING)


def fmt_validation_error(message):
    """Format the validation error message from the TOSCA parser.

    :mod:`toscaparser` concatenates exceptions with their
    tracebacks. Concatenated exceptions are then saved as
    an error message. As we do not want the tracebacks in
    errors that are send to the end-users, the tracebacks
    have to be filtered from the validation error messages.

    Args:
        message (str): Message to format.

    Returns:
        str: Formatted error message (without tracebacks).

    """
    formatted_message = []
    lines = message.splitlines()
    for line in lines:
        if "\t\t" in line or not line:
            continue

        formatted_message.append(line.strip())

    return "\n".join(formatted_message)


class ToscaException(Exception):
    """Base exception for the tosca module."""


class ToscaParserException(ToscaException):
    """Exception raised when an error occurs during
    the :class:`ToscaParser` translation.
    """

    def __init__(self, error, formatter=None):
        if formatter:
            error.message = formatter(error.message)

        super().__init__(error)


class ToscaParser(object):
    """The Tosca parser is comprisesed of basic TOSCA related tools for TOSCA template processing.

    It contains the TOSCA parser and validator from  :mod:`toscaparser` and
    a custom translator, that can translate TOSCA templates to
    the Kubernetes manifests. The translation expects, that the
    TOSCA custom type `tosca.nodes.indigo.KubernetesObject` is used.

    TOSCA could be loaded from the following sources:
    - Python dict
    - TOSCA template **file** with `yml` or `yaml` suffix
      - this can be loaded from the local filesystem or
        downloaded from a remote location defined by a URL
    - Cloud Service Archive (CSAR) **file** with `zip` or `csar` suffix
      - this can be loaded from the local filesystem or
        downloaded from a remote location defined by URL

    Example:
        .. code:: python

            from krake.data.tosca import ToscaParser

            manifest = {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "name": "pi",
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "pi",
                                "image": "perl:5.34.0",
                                "command": ["perl", "-Mbignum=bpi", "-wle", "print bpi(2000)"],  # noqa: E501
                            }
                        ]
                    }
                },
            }
            tosca = {
                "tosca_definitions_version": "tosca_simple_yaml_1_0",
                "imports": [
                    {
                        "ec3_custom_types": "https://raw.githubusercontent.com/grycap/ec3/tosca/tosca/custom_types.yaml"  # noqa: E501
                    }
                ],
                "topology_template": {
                    "node_templates": {
                        "pi-job": {
                            "type": "tosca.nodes.indigo.KubernetesObject",
                            "properties": {"spec": manifest},
                        }
                    }
                },
            }
            # From dict
            tosca_parsed = ToscaParser.from_dict(tosca)
            assert tosca_parsed.translate_to_manifests() == [manifest]

            # From path
            with open('tosca.yaml', 'w') as file:
                yaml.dump(tosca, file)
            tosca_parsed = ToscaParser.from_path('tosca.yaml')
            assert tosca_parsed.translate_to_manifests() == [manifest]

            # From URL
            # Upload the file to the remote location, e.g. https://example.com/tosca.yaml
            tosca_parsed = ToscaParser.from_url('https://example.com/tosca.yaml')
            assert tosca_parsed.translate_to_manifests() == [manifest]

    Attributes:
        yaml_dict_tpl (dict, optional): TOSCA template serialized as Python dict.
        path (str, optional): TOSCA template path or CSAR path.
        url (str, optional): TOSCA template URL or CSAR URL.

    """

    def __init__(self, yaml_dict_tpl=None, path=None, url=None):
        if not any([yaml_dict_tpl, path, url]):
            raise ToscaParserException(
                "TOSCA should be defined by a python dict, filename or a URL"
            )

        self.tosca_template = self._get_tosca_template(yaml_dict_tpl, path, url)

    @classmethod
    def from_dict(cls, yaml_dict_tpl):
        """Load a TOSCA template from a dictionary.

        Args:
            yaml_dict_tpl (dict): TOSCA template.

        Returns:
            ToscaParser: Tosca parser instance.

        """
        return cls(yaml_dict_tpl=yaml_dict_tpl)

    @classmethod
    def from_path(cls, path):
        """Load a TOSCA template file or a CSAR file.

        Args:
            path (str): Path to the TOSCA or CSAR file.

        Returns:
            ToscaParser: Tosca parser instance.

        """
        return cls(path=path)

    @classmethod
    def from_url(cls, url):
        """Load a TOSCA template file or a CSAR file from a URL.

        Args:
            url (str): URL to the TOSCA or CSAR file.

        Returns:
            ToscaParser: Tosca parser instance.

        """
        return cls(url=url)

    @staticmethod
    def _get_tosca_template(yaml_dict_tpl=None, path=None, url=None):
        """Returns a parsed TOSCA template.

        Args:
            yaml_dict_tpl (dict, optional): TOSCA template dict to be parsed.
            path (str, optional): TOSCA template path or CSAR path to be parsed.

        Returns:
            ToscaTemplate: Parsed tosca template.

        Raises:
            ToscaParserException: When tosca validation failed.

        """
        if yaml_dict_tpl:
            try:
                return ToscaTemplate(yaml_dict_tpl=yaml_dict_tpl)
            except ValidationError as err:
                raise ToscaParserException(err, formatter=fmt_validation_error)

        if path or url:
            a_file = not url
            try:
                return ToscaTemplate(path=path or url, a_file=a_file)
            except ValidationError as err:
                raise ToscaParserException(err, formatter=fmt_validation_error)

    def _get_manifest(self, tosca_tpl, node, property_value):
        """Get manifests recursively from TOSCA templates.

        TOSCA node template is recursively translated to the k8s manifest.
        The recursion here is required because of TOSCA functions that
        can be applied to the templates.
        Currently supported functions in :func:`_get_manifest` are:
        - get_property
        - get_input
        - concat

        Args:
            tosca_tpl (ToscaTemplate): TOSCA template instance.
            node (toscaparser.nodetemplate.NodeTemplate): Node to translate.
            property_value (raw): Property value.

        Returns:
            str: Kubernetes manifest.

        Raises:
            ToscaParserException: If the TOSCA function used in the TOSCA template
                is not supported yet.

        """
        manifest = ""

        _func = get_function(
            tosca_tpl=tosca_tpl, node_template=node, raw_function=property_value
        )

        if is_function(_func):
            if isinstance(_func, Concat):
                for item in _func.args:
                    manifest += self._get_manifest(tosca_tpl, node, item)

            elif isinstance(_func, GetInput):
                input_obj, *_ = [
                    input_def
                    for input_def in tosca_tpl.inputs
                    if _func.input_name == input_def.name
                ]
                manifest += " " + str(input_obj.default)

            elif isinstance(_func, GetProperty):
                manifest += self._get_manifest(tosca_tpl, node, _func.result())

            else:
                raise ToscaParserException(
                    f"Function {_func.name} is not supported by"
                    " the Krake TOSCA engine yet."
                )

        else:
            manifest += _func

        return manifest

    def translate_to_manifests(self):
        """Translate a TOSCA template to Kubernetes manifests.

        Returns:
            list: List of Kubernetes manifests.

        Raises:
            ToscaParserException: If the unsupported TOSCA node is used or
                the TOSCA node has an empty `spec` property.

        """
        manifests = []
        tosca_template = self.tosca_template

        if not hasattr(tosca_template, "nodetemplates"):
            raise ToscaParserException("TOSCA does not contain any topology template.")

        if not tosca_template.nodetemplates:
            raise ToscaParserException("TOSCA does not contain any node template.")

        for node in tosca_template.nodetemplates:

            if node.type != "tosca.nodes.indigo.KubernetesObject":
                raise ToscaParserException(
                    f"The TOSCA node type {node.type} is not supported by"
                    " the Krake TOSCA engine yet."
                )

            spec = node.get_property_value("spec")
            if not spec:
                raise ToscaParserException(
                    "TOSCA node property `spec` must not be empty."
                )
            try:
                manifest_str = self._get_manifest(tosca_template, node, spec)
            except (TOSCAException, TypeError, ValueError) as err:
                raise ToscaParserException(err)

            try:
                manifest = yaml.safe_load(manifest_str)
            except yaml.YAMLError as err:
                raise ToscaParserException(err)
            else:
                manifests.append(manifest)

        return manifests
