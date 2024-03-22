from enum import Enum

INVALID_SHUTDOWN_FAILURE_STRATEGY_ERROR = 'invalid shutdown hook failure strategy'


class ShutdownHookFailureStrategy(Enum):
    """ Strategy to execute after the shutdown of an application with a shutdown hook
      failed

    Attributes:
        GIVE_UP: Do nothing and let the user manually remove the application
        DELETE: Force delete application from the kubernetes cluster and the database.
            Warning: This is a destructive action
    """

    GIVE_UP = 'give_up'
    DELETE = 'delete'

    @staticmethod
    def _list_supported_values() -> str:
        return list(map(lambda c: c.value, ShutdownHookFailureStrategy))

    @staticmethod
    def enusure_supported_value(strategy: str):
        """ check if given string name can be used to instantiate enum
        """
        if strategy not in ShutdownHookFailureStrategy._value2member_map_:
            raise ValueError(f"{strategy!r} is"
                             f"{INVALID_SHUTDOWN_FAILURE_STRATEGY_ERROR}. "
                             f"Supported values are"
                             f"{ShutdownHookFailureStrategy.list_supported_values()}")
