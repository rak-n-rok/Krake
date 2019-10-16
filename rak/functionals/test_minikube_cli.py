from utils import run


def test_list_krake_applications():
    cmd = "kubectl get po --all-namespaces"
    response = run(cmd)

    assert response.returncode == 0
    assert "NAMESPACE" in response.output
