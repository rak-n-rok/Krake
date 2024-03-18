from enum import Enum

#region Constants
VALIDATE_POSITIVE_INT_ERROR = "Must be int greater than 0"
#endregion

#region Methods
# def validate_enum(enum_type: Enum, value: str):
#     """Ensure that value can be converted to the given Enum

#     Args:
#         enum_type (Enum): the Enum Type value should be converted to
#         value (str): value that should be converted to Enum enum_type

#     Raises:
#         ValueError: if value cannot be converted to enum_type
#     """

def validate_positive_int(number: int) -> bool:
    """Ensure that the provided parameter is an int > 0

    Args:
        number (int): the endpoint to verify.

    Raises:
        ValueError: if number is not an int or <= 0

    """
    return isinstance(number, int) and number > 0
    
#endregion

