from functools import reduce
import ipaddress
import random

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization as crypto_serialization


def ssh_ed25519_key_pair_factory():
    """Create an ed25519 key pair

    Returns:
        Tuple[str, str]: a tuple with the private and public key in OpenSSH format.
    """

    ed25519_private_key = ed25519.Ed25519PrivateKey.generate()

    return (
        # serialized private key
        ed25519_private_key.private_bytes(
            encoding=crypto_serialization.Encoding.PEM,
            format=crypto_serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=crypto_serialization.NoEncryption(),
        ).decode("utf-8"),
        # serialized public key
        crypto_serialization.ssh.serialize_ssh_public_key(
            ed25519_private_key.public_key()
        ).decode("utf-8"),
    )


def test_net_ip_address_generator(n=1):
    rfc5737_test_nets = list(
        map(
            lambda net: ipaddress.ip_network(net),
            ["192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"],
        )
    )

    ips = reduce(
        lambda a, b: a + b, [[ip for ip in net.hosts()] for net in rfc5737_test_nets]
    )

    for _ in range(n):
        yield str(random.choice(ips))
