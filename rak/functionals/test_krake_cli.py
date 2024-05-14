from functionals.utils import run


def test_list_krake_applications():
    cmd = "krakectl kube app list"
    response = run(cmd)
    try:
        assert response.returncode == 0
    except AssertionError:
        print(response.output)
        assert False
    assert "name" in response.output
