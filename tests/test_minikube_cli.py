import util


def test_list_krake_applications():
    cmd = "kubectl get po --all-namespaces"
    response = util.run(cmd)

    assert "NAMESPACE" in response.output
