import util


def test_list_krake_applications():
    cmd = "kubectl get po --all-namespaces"
    response = util.run(cmd)
    util.logger.debug(f"Response from the command: \n{response}")

    assert "NAMESPACE" in response
