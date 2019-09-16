#!/usr/bin/python3
"""
Generates config for krake scheduler.
Please don't replace "_" with "-" in the filename. This file is imported as a module in python tests.
Python module name should not contain dashes. https://www.python.org/dev/peps/pep-0008/#package-and-module-names
"""

import sys
import ast
import pprint


def generate_config(config: dict) -> dict:
    """
    Generates config for krake scheduler.

    :param config: config parameters
    :return: config in required format
    """

    return {
        'deployment_uuid': config['deployment_uuid'],
        'deployment_backend': config['deployment_backend'],
        'identity_provider_auth_url': 'https://' + config['deployment_ip'] + '/identity/v3',
        'prometheus_url': 'https://' + config['deployment_ip'] + ':44301/prometheus/api/v1/query',
        'federated_project_uuid': config['federated_project_uuid'],
    }


OPENSTACK_INSTANCES = []
DEPLOYMENTS = []

if __name__ == "__main__" and len(sys.argv) >= 2:
    OPENSTACK_INSTANCES = ast.literal_eval(sys.argv[1])

for hostname in OPENSTACK_INSTANCES:
    DEPLOYMENTS.append(generate_config(hostname))

print("DEPLOYMENTS = {}".format(pprint.pformat(DEPLOYMENTS)))
print("""
DEPLOYMENT_METRICS = {
    'common': ['krake_metric'],
    'OpenStack': ['openstack_total_free_vcpus', 'openstack_total_free_ram_MB'],
    'Kubernetes': ['kube_pod_container_status_running']
}""")
print("""
DEPLOYMENT_EXPORTERS = {
    'common': 'dummy-exporter',
    'OpenStack': 'openstack-exporter',
    'Kubernetes': 'kubernetes-pods'
}""")
print("""
DEPLOYMENT_FLAVORS = {
    'ds1G': {
        'ram': 1024,  # [MB]
        'vcpus': 1
    }
}""")
print("""
KUBERNETES_PODS_MAX = 15
""")
