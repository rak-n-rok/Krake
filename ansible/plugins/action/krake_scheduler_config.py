import json
from string import Template

from ansible.plugins.action import ActionBase
from ansible.errors import AnsibleError


template = Template("""
DEPLOYMENTS = $deployments

# Deployment metrics priority is defined by order in the list. Highest priority first.
DEPLOYMENT_METRICS = {
    'common': ['krake_metric'],
    'OpenStack': ['openstack_total_free_vcpus', 'openstack_total_free_ram_MB'],
    'Kubernetes': ['kube_pod_container_status_running']
}

DEPLOYMENT_EXPORTERS = {
    'common': 'dummy-exporter',
    'OpenStack': 'openstack-exporter',
    'Kubernetes': 'kubernetes-exporter'
}

DEPLOYMENT_FLAVORS = {
    "ds1G": {
        "ram": 1024,  # [MB]
        "vcpus": 1
    }
}

KUBERNETES_PODS_MAX = 20
""")


class ActionModule(ActionBase):

    def run(self, tmp=None, task_vars=None):
        try:
            devstacks = self._task.args['devstacks']
            clusters = self._task.args['magnum_clusters']
        except KeyError as e:
            raise AnsibleError("Parameter '{}' is required".format(e))

        openstack_deployments = [configure_openstack(devstack, task_vars) for devstack in devstacks]
        preset_clusters = [configure_kubernetes(cluster, task_vars) for cluster in clusters]

        # We use a string.Template here instead of standard Python format
        # strings because the Python code in the template ("{ … }") would be
        # interpreted as format parameters.
        config = template.substitute(deployments=json.dumps(openstack_deployments + preset_clusters, indent=4))

        return {
            'changed': True,
            'config': config
        }


def configure_openstack(deployment, taskvars):
    """Fetch all required configuration parameters for a DevStack deployment
    given by its Ansible inventory name.

    Args:
        deployment (str): Ansible inventory name of deployment instance
        taskvars (dict): Ansible task variables

    Returns:
        dict: Configuration for a single DevStack deployment that is used
        by Krake

    """
    hostvars = taskvars['hostvars'][deployment]

    # Private IP address of the DevStack instance
    ip = hostvars['private_ip']

    # Federated project UUID
    federated_project_uuid = hostvars['federated_project_uuid']

    deployment_uuid = 'sp_devstack{id}'.format(id=hostvars['id'])

    auth_url = 'https://{ip}:{port}/identity/v3'.format(
        ip=ip,
        port=hostvars['service_provider_port']
    )

    prometheus_url = 'https://{ip}:{port}/prometheus/api/v1/query'.format(
        ip=ip,
        port=hostvars['prometheus_port']
    )

    return {
        'deployment_uuid': deployment_uuid,
        'deployment_backend': 'OpenStack',
        'identity_provider_auth_url': auth_url,
        'prometheus_url': prometheus_url,
        'federated_project_uuid': federated_project_uuid,
    }


def configure_kubernetes(deployment, taskvars):
    """Fetch all required configuration parameters for a preset OpenStack
    Kubernetes cluster given by its Ansible inventory name.

    Args:
        deployment (str): Ansible inventory name of preset OpenStack Kubernetes
            cluster instance.
        taskvars (dict): Ansible task variables

    Returns:
        dict: Configuration for a single preset OpenStack Kubernetes cluster
        that is used by Krake

    """
    hostvars = taskvars['hostvars'][deployment]
    devstack_hostvars = taskvars['hostvars'][hostvars['devstack']]

    # Private IP address of the DevStack instance
    devstack_ip = devstack_hostvars['private_ip']

    # Federated project UUID
    federated_project_uuid = devstack_hostvars['federated_project_uuid']

    deployment_uuid = 'sp_{name}'.format(name=hostvars['name'])

    auth_url = 'https://{ip}:{port}/identity/v3'.format(
        ip=devstack_ip,
        port=devstack_hostvars['service_provider_port']
    )

    prometheus_url = 'https://{ip}:{port}/prometheus/api/v1/query'.format(
        ip=hostvars['ansible_host'],
        port=hostvars['prometheus_port']
    )

    return {
        'deployment_uuid': deployment_uuid,
        'deployment_backend': 'Kubernetes',
        'identity_provider_auth_url': auth_url,
        'prometheus_url': prometheus_url,
        'federated_project_uuid': federated_project_uuid,
    }
