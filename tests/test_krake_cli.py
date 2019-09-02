import util
import logging

logging.basicConfig(level=logging.DEBUG)


def test_list_krake_applications():
    cmd = "rok kube app list"
    response = util.run(cmd)
    logging.info("response from the command: %s\n", response)

    assert "name" in response
