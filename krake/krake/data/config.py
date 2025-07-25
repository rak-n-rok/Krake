from typing import List

from dataclasses import field
from krake.data.core import Role, RoleBinding
from krake.data.serializable import Serializable
from marshmallow import ValidationError
from yarl import URL

from krake.data.hooks.enums import ShutdownHookFailureStrategy
from krake.validation import validate_non_negative_int, validate_positive_int


class TlsConfiguration(Serializable):
    enabled: bool = field(
        default=False, metadata={"help": "Enable TLS client certificate authentication"}
    )
    client_ca: str = field(metadata={"help": "Path to the CA certificate."})


class TlsClientConfiguration(TlsConfiguration):
    client_cert: str = field(metadata={"help": "Path to the client certificate."})
    client_key: str = field(metadata={"help": "Path to the client certificate key."})


class TlsServerConfiguration(TlsConfiguration):
    cert: str = field(metadata={"help": "Path to the server certificate."})
    key: str = field(metadata={"help": "Path to the server certificate key."})


class EtcdConfiguration(Serializable):
    host: str = field(
        default="127.0.0.1", metadata={"help": "Address of the etcd database."}
    )
    port: int = field(
        default=2379, metadata={"help": "Port to connect to the etcd database."}
    )
    retry_transactions: int = field(
        default=1,
        metadata={
            "help": "Number of retry for a transaction with the database that failed."
        },
    )


class DocsConfiguration(Serializable):
    problem_base_url: str = field(
        default=(
            "https://rak-n-rok.readthedocs.io/projects/krake/en/latest/user/problem.html"  # noqa: E501
        ),
        metadata={"help": "URL of the problem documentation."},
    )


class KeystoneAuthenticationConfiguration(Serializable):
    enabled: bool = field(
        default=False, metadata={"help": "If true, enables the Keystone authentication"}
    )
    endpoint: str = field(
        default="http://localhost:5000/v3",
        metadata={"help": "Endpoint to connect to the Keystone service"},
    )


class KeycloakAuthenticationConfiguration(Serializable):
    enabled: bool = field(
        default=False, metadata={"help": "If true, enables the Keycloak authentication"}
    )
    endpoint: str = field(
        default="http://localhost:9080",
        metadata={"help": "Endpoint to connect to the Keycloak service"},
    )
    realm: str = field(
        default="krake",
        metadata={
            "help": "Keycloak realm against which the user should be authenticated"
        },
    )


class StaticAuthenticationConfiguration(Serializable):
    enabled: bool = field(
        default=False, metadata={"help": "If true, enables the static authentication"}
    )
    name: str = field(
        default="system",
        metadata={
            "help": "Name of the user that will be used with static authentication."
        },
    )


class StrategyConfiguration(Serializable):
    keystone: KeystoneAuthenticationConfiguration
    keycloak: KeycloakAuthenticationConfiguration
    static: StaticAuthenticationConfiguration


class AuthenticationConfiguration(Serializable):
    cors_origin: str = field(
        default="*",
        metadata={"help": "Set the 'Access-Control-Allow-Origin' CORS field."},
    )
    allow_anonymous: bool = field(
        default=False,
        metadata={"help": "If set, Krake will accept anonymous requests."},
    )
    strategy: StrategyConfiguration


class AutomaticClusterCreationConfiguration(Serializable):
    tosca_file: str = field(
        default="examples/automation/cluster.yaml",
        metadata={
            "help": "Location of the tosca file to automatically create a cluster"
        },
    )
    deletion_retention: int = field(
        default=600,
        metadata={
            "help": "Time until the deletion of an empty generated cluster is started."
        },
    )


def _validate_endpoint(endpoint):
    """Ensure that the provided endpoint is a valid URL and that it has a supported
    scheme.

    Args:
        endpoint (str): the endpoint to verify.

    Returns:
        True if the endpoint is valid.

    Raises:
        ValidationError: if the URL or its scheme is unsupported.

    """
    endpoint_url = URL(endpoint)

    message = (
        "A scheme should be provided with the external endpoint. Current value:"
        f" {str(endpoint_url)!r}."
    )
    if not endpoint_url.scheme:
        raise ValidationError(message)

    # yarl considers the host (IP address or hostname) to be the scheme if a port
    # and a path are added to the endpoint.
    # Example: URL('1.2.3.4:80/test').scheme -> "1.2.3.4"
    if not endpoint_url.host:
        raise ValidationError(message)

    scheme = endpoint_url.scheme
    if scheme not in ["http", "https"]:
        raise ValidationError(f"The provided scheme {scheme!r} is not supported.")

    return True


# region Hooks
class CompleteHookConfiguration(Serializable):
    hook_user: str = field(
        default="system:complete-hook",
        metadata={
            "help": (
                "Name of the 'complete' hook user put in the certificates given to"
                " Applications. Needed if RBAC is enabled."
            )
        },
    )
    intermediate_src: str = field(
        metadata={
            "help": (
                "Path to the certificate which will sign new certificates given to the"
                " Applications."
            )
        }
    )
    intermediate_key_src: str = field(
        metadata={
            "help": (
                "Path to the certificate key which will sign new certificates given"
                " to the Applications."
            )
        }
    )
    cert_dest: str = field(
        default="/etc/krake_complete_certs/",
        metadata={
            "help": "Environment variable to be used in the Kubernetes Application"
        },
    )
    env_token: str = field(
        default="KRAKE_COMPLETE_TOKEN",
        metadata={
            "help": (
                "Name of the environment variable to be used in the Kubernetes"
                " Application to access the token to identify the Application."
            )
        },
    )
    env_url: str = field(
        default="KRAKE_COMPLETE_URL",
        metadata={
            "help": (
                "Name of the environment variable to be used in the Kubernetes"
                " Application to access the actual API endpoint of Krake to notify the"
                " end of job."
            )
        },
    )
    external_endpoint: str = field(
        default=None,
        metadata={
            "help": (
                "URL that will be provided to the Application, which corresponds to the"
                " API endpoint to notify the end of job. If not provided, the default"
                " endpoint of the Krake API will be used. It should be set if the"
                " KubernetesController is connected to the API with a private IP."
            ),
            "validate": _validate_endpoint,
        },
    )


class ShutdownHookConfiguration(Serializable):
    hook_user: str = field(
        default="system:shutdown-hook",
        metadata={
            "help": (
                "Name of the 'shutdown' hook user put in the certificates given to"
                " Applications. Needed if RBAC is enabled."
            )
        },
    )
    intermediate_src: str = field(
        metadata={
            "help": (
                "Path to the certificate which will sign new certificates given to the"
                " Applications."
            )
        }
    )
    intermediate_key_src: str = field(
        metadata={
            "help": (
                "Path to the certificate key which will sign new certificates given"
                " to the Applications."
            )
        }
    )
    cert_dest: str = field(
        default="/etc/krake_shutdown_certs/",
        metadata={
            "help": "Environment variable to be used in the Kubernetes Application"
        },
    )
    env_token: str = field(
        default="KRAKE_SHUTDOWN_TOKEN",
        metadata={
            "help": (
                "Name of the environment variable to be used in the Kubernetes"
                " Application to access the token to identify the Application."
            )
        },
    )
    env_url: str = field(
        default="KRAKE_SHUTDOWN_URL",
        metadata={
            "help": (
                "Name of the environment variable to be used in the Kubernetes"
                " Application to access the actual API endpoint of Krake to notify the"
                " end of job."
            )
        },
    )
    external_endpoint: str = field(
        default=None,
        metadata={
            "help": (
                "URL that will be provided to the Application, which corresponds to the"
                " API endpoint to notify the end of job. If not provided, the default"
                " endpoint of the Krake API will be used. It should be set if the"
                " KubernetesController is connected to the API with a private IP."
            ),
            "validate": _validate_endpoint,
        },
    )
    timeout: int = field(
        default=30,
        metadata={
            "help": (
                "Timeout after calling the shutdown of the application until the"
                " application requests a shutdown from the Krake API. If a timeout"
                " occurs, the given failure strategy will be exectued."
            ),
            "validate": validate_positive_int,
        },
    )
    failure_strategy: str = field(
        default=ShutdownHookFailureStrategy.DELETE.value,
        metadata={
            "help": (
                "Strategy to execute after a shutdown timeout occured"
                "Supported values:"
                "'delete': Remove the application"
                " failure_retry_count times"
                "'give_up': Do nothing and let the user manually shut down the"
                " application"
            ),
            "validate": ShutdownHookFailureStrategy.enusure_supported_value,
        },
    )
    failure_retry_count: int = field(
        default=0,
        metadata={
            "help": (
                "Maximum number of retries to gracefully shutdown the application until"
                "the specified failure strategy is executed"
            ),
            "validate": validate_non_negative_int,
        },
    )


class HooksConfiguration(Serializable):
    complete: CompleteHookConfiguration
    shutdown: ShutdownHookConfiguration


class MigrationRetryConfiguration(Serializable):
    max: int = field(
        default=10,
        metadata={
            "help": (
                "Maximum number of retries for the transfer of "
                "a single file of an application"
            )
        },
    )
    timeout: int = field(
        default=60,
        metadata={"help": "Timeout after a failed migration for the next rescheduling"},
    )


# endregion


class MigrationConfiguration(Serializable):
    retry: MigrationRetryConfiguration


###################################
#    Components configurations    #
###################################


class ControllerConfiguration(Serializable):
    api_endpoint: str = field(
        default="http://localhost:8080",
        metadata={"help": "URL to the Krake API server"},
    )
    worker_count: int = field(
        default=5,
        metadata={"help": "Number of workers that are used to handle state changes"},
    )
    debounce: float = field(
        default=1.0,
        metadata={"help": "Number of seconds to wait until a state change is handled"},
    )
    tls: TlsClientConfiguration
    # FIXME: this dict should be replaced by a fixed set of well-defined options.
    #  see issue #282
    log: dict


class SchedulerConfiguration(ControllerConfiguration):
    reschedule_after: float = field(
        default=60,
        metadata={"help": "Time in seconds after which resources get rescheduled"},
    )
    stickiness: float = field(
        default=0.1,
        metadata={
            "help": "Additional weight for the ranking calculation, "
            "to prevent too frequent rescheduling"
        },
    )
    automatic_cluster_creation: AutomaticClusterCreationConfiguration


class KubernetesConfiguration(ControllerConfiguration):
    hooks: HooksConfiguration


class KubernetesApplicationConfiguration(KubernetesConfiguration):
    migration: MigrationConfiguration


class MagnumConfiguration(ControllerConfiguration):
    poll_interval: float = field(
        default=30,
        metadata={
            "help": "Time in seconds to wait between two requests to the Magnum "
            "client, to get a Magnum cluster new state after modification."
        },
    )


class InfrastructureConfiguration(ControllerConfiguration):
    poll_interval: float = field(
        default=30,
        metadata={
            "help": "Time in seconds to wait between two requests to the"
            " infrastructure provider client, to get an infrastructure"
            " new state after modification."
        },
    )


class ApiConfiguration(Serializable):
    host: str = field(
        default="localhost",
        metadata={"help": "Host IP address or 'localhost' to expose the Krake API at."},
    )
    port: int = field(
        default=8080, metadata={"help": "Port to which the Krake API listens to."}
    )
    etcd: EtcdConfiguration
    docs: DocsConfiguration
    tls: TlsServerConfiguration
    authentication: AuthenticationConfiguration
    authorization: str = field(metadata={"help": "Authorization mode"})
    default_roles: List[Role] = field(default_factory=list)
    default_role_bindings: List[RoleBinding] = field(default_factory=list)
    log: dict
