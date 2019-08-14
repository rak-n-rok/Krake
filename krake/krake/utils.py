import re


def camel_to_snake_case(name):
    """Converts camelCase to the snake_case

    Args:
        name (str): Camel case name

    Returns:
        str: Name in stake case

    """
    cunder = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", cunder).lower()
