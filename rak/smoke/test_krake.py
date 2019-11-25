import json


def test_list_kubernetes_applications(host):
    apps = json.loads(
        host.check_output("/home/krake/.local/bin/rok kube app list -f json")
    )
    assert len(apps["items"]) == 0, "No apps are running"
