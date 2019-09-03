import util
import logging

logging.basicConfig(level=logging.DEBUG)


def test_list_krake_applications():
    cmd = "kubectl get po --all-namespaces"
    response = util.run(cmd)
    logging.info("response from the command: %s\n", response)

    assert "NAMESPACE" in response
