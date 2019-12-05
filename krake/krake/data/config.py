from typing import List

from dataclasses import field
from krake.data.core import Role, RoleBinding
from krake.data.serializable import Serializable


class TLSConfiguration(Serializable):
    enabled: bool = field(
        default=False, metadata={"help": "Enable TLS client certificate authentication"}
    )
    client_ca: str = field(metadata={"help": "Path to the CA certificate."})
    client_cert: str = field(metadata={"help": "Path to the client certificate."})
    client_key: str = field(metadata={"help": "Path to the client certificate key."})


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


class KeystoneAuthenticationConfiguration(Serializable):
    enabled: bool = field(
        default=False, metadata={"help": "If true, enables the Keystone authentication"}
    )
    endpoint: str = field(
        default="http://localhost:5000/v3",
        metadata={"help": "Endpoint to connect to the Keystone service"},
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
    static: StaticAuthenticationConfiguration


class AuthenticationConfiguration(Serializable):
    allow_anonymous: bool = field(
        default=False,
        metadata={"help": "If set, Krake will accept anonymous requests."},
    )
    strategy: StrategyConfiguration


class CompleteHookConfiguration(Serializable):
    ca_dest: str = field(
        default="/etc/krake_ca/ca.pem",
        metadata={
            "help": "Environment variable to be used in the Kubernetes Application"
        }
    )
    env_token: str = field(
        default="KRAKE_TOKEN",
        metadata={
            "help": (
                "Name of the environment variable to be used in the Kubernetes"
                "Application to access the token to identify the Application."
            )
        }
    )
    env_complete: str = field(
        default="KRAKE_COMPLETE_URL",
        metadata={
            "help":
                (
                    "Name of the environment variable to be used in the Kubernetes"
                    "Application to access the actual API endpoint of Krake to notify"
                    "the end of job."
                )
        }
    )


class HooksConfiguration(Serializable):
    complete: CompleteHookConfiguration


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
    tls: TLSConfiguration
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


class KubernetesConfiguration(ControllerConfiguration):
    hooks: HooksConfiguration


class ApiConfiguration(Serializable):
    etcd: EtcdConfiguration
    tls: TLSConfiguration
    authentication: AuthenticationConfiguration
    authorization: str = field(metadata={"help": "Authorization mode"})
    default_roles: List[Role] = field(default_factory=list)
    default_role_bindings: List[RoleBinding] = field(default_factory=list)
    log: dict
