"""Simple metrics exporter server exposes heat demand metrics also in minimal
configuration suitable for end-to-end testing of Krake infrastructure.

Metrics exporter generates random heat demand metrics for multiple zones.
Default number of zones is 5: `heat_demand_zone_1` .. `heat_demand_zone_5`.
Random heat demand metric value is regenerated (each 10s) from interval :
     <`zone_number` - 1, `zone_number`)

.. code:: bash

    $ python3 metric_exporter.py
    $ curl -s curl localhost:9091/metrics
    ...
    # HELP heat_demand_zone_1 float - heat demand (kW)
    # TYPE heat_demand_zone_1 gauge
    heat_demand_zone_1 0.7
    # HELP heat_demand_zone_2 float - heat demand (kW)
    # TYPE heat_demand_zone_2 gauge
    heat_demand_zone_2 1.22
    # HELP heat_demand_zone_3 float - heat demand (kW)
    # TYPE heat_demand_zone_3 gauge
    heat_demand_zone_3 2.59
    # HELP heat_demand_zone_4 float - heat demand (kW)
    # TYPE heat_demand_zone_4 gauge
    heat_demand_zone_4 3.81
    # HELP heat_demand_zone_5 float - heat demand (kW)
    # TYPE heat_demand_zone_5 gauge
    heat_demand_zone_5 4.54

"""
import asyncio
import functools
import random
from argparse import ArgumentParser

from aiohttp import web
from prometheus_async import aio
from prometheus_client import Gauge


CYCLE_INTERVAL = 10


async def heat_demand_metric(zone):
    metric = Gauge(f"heat_demand_zone_{zone}", "float - heat demand (kW)")
    while True:
        metric.set(round(random.uniform(zone - 1, zone), 2))
        await asyncio.sleep(CYCLE_INTERVAL)


async def start_metrics_tasks(zones, app):
    app["metrics"] = [
        asyncio.get_event_loop().create_task(heat_demand_metric(zone))
        for zone in range(1, zones + 1)
    ]


async def cleanup_metrics_tasks(app):
    for task in app["metrics"]:
        task.cancel()
    await app["metrics"]


async def exporter(host, port, zones):

    app = web.Application()
    app.router.add_get("/metrics", aio.web.server_stats)
    app.on_startup.append(functools.partial(start_metrics_tasks, zones))
    app.on_cleanup.append(cleanup_metrics_tasks)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()


parser = ArgumentParser(
    description="Metrics exporter server."
)
parser.add_argument(
    "--host",
    type=str,
    default="0.0.0.0",
    help="Exporter port to expose metrics. Default: 0.0.0.0",
)
parser.add_argument(
    "--port",
    type=int,
    default=9091,
    help="Exporter port to expose metrics. Default: 9091",
)
parser.add_argument(
    "--zones", type=int, default=5, help="Head demand metrics zone count Default: 5"
)


if __name__ == "__main__":
    args = parser.parse_args()
    loop = asyncio.get_event_loop()
    loop.create_task(exporter(args.host, args.port, args.zones))
    loop.run_forever()
