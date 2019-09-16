from ipaddress import ip_network


def network_address(cidr):
    return ip_network(cidr).network_address


def netmask(cidr):
    return ip_network(cidr).netmask


def network_hosts(cidr):
    return ip_network(cidr).hosts()


class FilterModule(object):

    def filters(self):
        return {
            'ipnetwork': ip_network,
            'network_address': network_address,
            'netmask': netmask,
            'network_hosts': network_hosts,
        }
