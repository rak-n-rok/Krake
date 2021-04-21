from functionals.utils import run


def test_list_krake_applications():
    cmd = "rok kube app list"
    response = run(cmd)

    assert response.returncode == 0
    assert "name" in response.output
