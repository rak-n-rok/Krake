import util


def test_list_krake_applications():
    cmd = "rok kube app list"
    response = util.run(cmd)
    util.logger.debug(f"Response from the command: \n{response}")

    assert "name" in response
