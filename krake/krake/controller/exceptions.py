"""Module for Krake controller responsible for error handling.
Defines common functionality for exceptions in Krake controller module.
"""
import logging
from functools import wraps


logger = logging.getLogger(__name__)


class ControllerError(Exception):
    """Base class for exceptions in this module."""

    code = 0

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
        code = f"[{str(self.code)}]" if self.code > 0 else ""

        return f"{type(self).__name__}{code}: {message}"


def on_error(exception):
    """Simple decorator factory for handling controller specific exceptions.

    When any exception defined by :param:`exception` occurs,
    then :meth: `error_occured` will be called as a callback of wrapped function.

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

            def error_occured(app, reason=None)
                ...

    """

    def decorator(func):
        @wraps(func)
        async def wrapper(cls, item, **kwargs):
            try:
                await func(cls, item, **kwargs)
            except exception as err:
                logger.error(str(err))
                await cls.error_occured(item, reason=err.message)

        return wrapper

    return decorator
