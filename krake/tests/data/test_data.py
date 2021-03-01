import pytest
from krake.data import Key
from krake.data.serializable import Serializable


def test_key_format_object():
    """Test the format_object method of :class:`Key`."""

    class Spaceship(Serializable):
        name: str
        namespace: str

    key = Key("/space/spaceship/{namespace}/{name}")

    spaceship = Spaceship(name="Rocinante", namespace="solar-system")

    etcd_key = key.format_object(spaceship)
    assert etcd_key == "/space/spaceship/solar-system/Rocinante"


def test_key_format_kwargs():
    """Test the format_kwargs method of :class:`Key`."""
    key = Key("/space/spaceship/{namespace}/{name}")

    # Valid parameters
    etcd_key = key.format_kwargs(name="Rocinante", namespace="solar-system")
    assert etcd_key == "/space/spaceship/solar-system/Rocinante"

    # Invalid parameters
    with pytest.raises(TypeError, match="Missing required keyword argument 'name'"):
        key.format_kwargs(namespace="galaxy")

    with pytest.raises(
        TypeError, match="Got unexpected keyword argument parameter 'propulsion'"
    ):
        key.format_kwargs(
            name="Enterprise", namespace="Universe", propulsion="warp-drive"
        )


def test_key_matches():
    """Test the matches method of :class:`Key`."""
    key = Key("/space/spaceship/{namespace}/{name}")

    # Valid matches
    assert key.matches("/space/spaceship/milky-way/Bebop")
    assert key.matches("/space/spaceship/Andromeda/heart_of_gold")

    # Invalid matches
    assert not key.matches("/space/spaceship/")
    assert not key.matches("/space/spaceship/rebels")
    assert not key.matches("/space/spaceship/empire/TIE/Fighter")
    assert not key.matches("/space/spaceship/empire/TIE|Fighter")
    assert not key.matches("/space/spaceship/empire/TIE Fighter")


def test_key_prefix():
    """Test the prefix method of :class:`Key`."""
    key = Key("/space/spaceship/{namespace}/{name}/{propulsion}")

    # Valid parameters
    assert key.prefix(namespace="belt") == "/space/spaceship/belt/"
    assert (
        key.prefix(namespace="belt", name="voyager") == "/space/spaceship/belt/voyager/"
    )

    # Invalid parameters
    with pytest.raises(
        TypeError, match="Got parameter 'name' without preceding parameter 'namespace'"
    ):
        key.prefix(name="Battlestar")

    with pytest.raises(
        TypeError, match="Got parameter 'propulsion' without preceding parameter 'name'"
    ):
        key.prefix(namespace="belt", propulsion="antimatter")
