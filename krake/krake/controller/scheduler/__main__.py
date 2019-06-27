"""Entry point of Krake scheduler.

.. code:: bash

    python -m krake.controller.scheduler --help

Configuration is loaded from the ``controllers.scheduler`` section:

.. code:: yaml

    controllers:
      scheduler:
        api_endpoint: http://localhost:8080
        worker_count: 5

"""
from argparse import ArgumentParser
from krake import load_config
from krake.controller import run
from . import Scheduler, SchedulerWorker


parser = ArgumentParser(description="Krake scheduler")
parser.add_argument("-c", "--config", help="Path to configuration YAML file")


def main():
    args = parser.parse_args()
    config = load_config(args.config)["controllers"]["scheduler"]
    scheduler = Scheduler(
        api_endpoint=config["api_endpoint"],
        worker_factory=SchedulerWorker,
        worker_count=config["worker_count"],
    )
    run(scheduler)


if __name__ == "__main__":
    main()
