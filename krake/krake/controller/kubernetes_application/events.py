"""This module defines the Event Dispatcher which emits events on registering
listeners.

"""

import yarl
from inspect import iscoroutinefunction
from typing import NamedTuple

from kubernetes_asyncio.client import Configuration
from kubernetes_asyncio.config.kube_config import KubeConfigLoader


class Event(NamedTuple):
    kind: str
    action: str


class EventDispatcher(object):
    """Simple wrapper around a registry of handlers associated to Events

    Events are characterized by a "kind" and an "action" (see :class:`Event`).
    Listeners for certain events can be registered via :meth:`on`. Registered
    listeners are executed if an event gets emitted via :meth:`emit`.

    Example:
        .. code:: python

        listen = EventDispatcher()

        @listen.on(Event("Deployment","delete"))
        def to_perform_on_deployment_delete(app, cluster, resp):
            # Do Stuff

        @listen.on(Event("Deployment","delete"))
        def another_to_perform_on_deployment_delete(app, cluster, resp):
            # Do Stuff

        @listen.on(Event("Service","apply"))
        def to_perform_on_service_apply(app, cluster, resp):
            # Do Stuff

    """

    def __init__(self):
        self.registry = {}

    def on(self, event):
        """Decorator function to add a new handler to the registry.

        Args:
            event (Event): Event for which to register the handler.

        Returns:
            callable: Decorator for registering listeners for the specified
            events.

        """

        def decorator(handler):
            if not (event.kind, event.action) in self.registry:
                self.registry[(event.kind, event.action)] = [handler]
            else:
                self.registry[(event.kind, event.action)].append(handler)

        return decorator

    async def emit(self, event, **kwargs):
        """ Execute the list of handlers associated to the provided Event.

        Args:
            event (Event): Event for which to execute handlers.

        """
        try:
            handlers = self.registry[(event.kind, event.action)]
        except KeyError:
            pass
        else:
            for handler in handlers:
                if iscoroutinefunction(handler):
                    await handler(**kwargs)
                else:
                    handler(**kwargs)


listen = EventDispatcher()


@listen.on(event=Event("Service", "apply"))
async def register_service(app, cluster, resp):
    service_name = resp.metadata.name

    node_port = resp.spec.ports[0].node_port

    if node_port is None:
        return

    # Load Kubernetes configuration and get host
    loader = KubeConfigLoader(cluster.spec.kubeconfig)
    config = Configuration()
    await loader.load_and_set(config)
    url = yarl.URL(config.host)

    app.status.services[service_name] = url.host + ":" + str(node_port)
