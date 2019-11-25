import json


def test_list_all_pods(host):
    pods = json.loads(host.check_output("kubectl get pod --all-namespaces -o json"))
    assert len(pods["items"]) > 0, "Pods are running"
