"""Base exceptions for use Krake-wide use."""


class ResourceHandlingError(Exception):
    """Base class for exceptions during handling of a resource."""

    code = None

    def __init__(self, message):
        super().__init__(message)
        self.message = message

    def __str__(self):
        """Custom error message for exception"""
        message = self.message or ""
        code = f"[{str(self.code)}]" if self.code is not None else ""

        return f"{self.__class__.__name__}{code}: {message}"
