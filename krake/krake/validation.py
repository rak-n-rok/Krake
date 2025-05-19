# region Constants
VALIDATE_POSITIVE_INT_ERROR = "Must be int greater than 0"
# endregion


# region Methods


def validate_positive_int(number: int) -> bool:
    """Ensure that the provided parameter is an int > 0

    Args:
        number (int): the endpoint to verify.

    Raises:
        ValueError: if number is not an int or <= 0

    """
    return isinstance(number, int) and number > 0


def validate_non_negative_int(number: int) -> bool:
    """Ensure that the provided parameter is an int >= 0

    Args:
        number (int): the endpoint to verify.

    Raises:
        ValueError: if number is not an int or <= 0

    """
    return isinstance(number, int) and number >= 0


# endregion
