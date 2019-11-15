"""Module for Krake controller responsible for error handling.
Defines common functionality for exceptions in Krake controller module.
"""
import logging
from functools import wraps

from krake.data.core import Reason, ReasonCode
from krake.data.kubernetes import ApplicationState

logger = logging.getLogger(__name__)


class ControllerError(Exception):
    """Base class for exceptions in this module."""

    code = ReasonCode.INTERNAL_ERROR

    def __init__(self, message=None, err_resp=None):
        super().__init__(message)

        if err_resp is not None:
            self.message = err_resp.reason
            self.code = err_resp.status
        else:
            self.message = message

    def __str__(self):
        """Custom error message for exception"""
        message = self.message or ""
        code = f"[{str(self.code.value)}]" if self.code is not None else ""

        return f"{type(self).__name__}{code}: {message}"


def on_error(exception):
    """Simple decorator factory for handling controller specific exceptions.

    When any exception defined by :param:`exception` occurs,
    then :meth: `error_occurred` will be called as a callback of wrapped function.

    Args:
        exception (Exception): Exception that calls wrapped function callback

    Example:
        .. code:: python

        class ControllerError(Exception):
            pass

        class CustomController(Controller):
            @on_error(ControllerError)
            def create_app(app):
                ...

            def error_occurred(app, error=None)
                ...

    """

    def decorator(func):
        @wraps(func)
        async def wrapper(cls, item, **kwargs):
            try:
                await func(cls, item, **kwargs)
            except exception as err:
                logger.error(str(err))
                await cls.error_handler(item, error=err)

        return wrapper

    return decorator


def application_error_mapping(previous_state, previous_reason, error=None):
    """
    Create a Reason with a specific ReasonCode depending on an Application state
    and the error sent.

    Args:
        previous_state (krake.data.kubernetes.ApplicationState): the state of the
        Application that triggered the error.
        previous_reason (krake.data.core.Reason):
        error (Exception): the exception raised

    Returns:
        Reason: a Reason with DELETE_FAILED code if the Application was in a
        FAILED State, the code of the Exception if it has one, or INTERNAL_ERROR code
        by default.

    """
    message = getattr(error, "message", "An exception was raised")
    # FIXME: added check for previous_reason as workaround, to delete FAILED
    #  application that were changed to DELETING state.
    #  Check moved first because the error may not have an error code when the
    #  application failed to delete
    if previous_state == ApplicationState.FAILED or previous_reason:
        return Reason(code=ReasonCode.DELETE_FAILED, message=message)

    if error is None or not hasattr(error, "code"):
        return Reason(code=ReasonCode.INTERNAL_ERROR, message="Internal Error")

    return Reason(code=error.code, message=message)
