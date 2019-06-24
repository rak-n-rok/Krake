"""Entry point of Kubernetes controller.

.. code:: bash

    python -m krake.controller.kubernetes --help

Configuration is loaded from the ``controllers.kubernetes`` section:

.. code:: yaml

    controllers:
      kubernetes:
        api_endpoint: http://localhost:8080
        worker_count: 5

"""
from argparse import ArgumentParser
from krake import load_config
from krake.controller import run
from . import KubernetesController, KubernetesWorker


parser = ArgumentParser(description="Kubernetes application controller")
parser.add_argument("-c", "--config", help="Path to configuration YAML file")


def main():
    args = parser.parse_args()
    config = load_config(args.config)["controllers"]["kubernetes"]
    scheduler = KubernetesController(
        api_endpoint=config["api_endpoint"],
        worker_factory=KubernetesWorker,
        worker_count=config["worker_count"],
    )
    run(scheduler)


if __name__ == "__main__":
    main()
