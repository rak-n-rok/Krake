"""Module for the common controller hook mechanism

Defines the HookDispatcher and listeners for registering and executing hooks.
HookDispatcher emits hooks based on :class:`Hook` attributes which define when the hook
will be executed.

Provides hooks that are shared between all controllers, such as the ones for observer
registration.
"""

import asyncio
from collections import defaultdict
from contextlib import suppress
from inspect import iscoroutinefunction
import logging

from krake.controller.kubernetes.hooks import (
    KubernetesApplicationObserver,
    KubernetesClusterObserver,
)
from krake.data.kubernetes import Application, Cluster


logger = logging.getLogger(__name__)


class HookDispatcher(object):
    """Simple wrapper around a registry of handlers associated to :class:`Hook`
     attributes. Each :class:`Hook` attribute defines when the handler will be
     executed.

    Listeners for certain hooks can be registered via :meth:`on`. Registered
    listeners are executed via :meth:`hook`.

    Example:
        .. code:: python

        listen = HookDispatcher()

        @listen.on(HookType.PreApply)
        def to_perform_before_app_creation(app, cluster, resource, controller):
            # Do Stuff

        @listen.on(HookType.PostApply)
        def another_to_perform_after_app_creation(app, cluster, resource, resp):
            # Do Stuff

        @listen.on(HookType.PostDelete)
        def to_perform_after_app_deletion(app, cluster, resource, resp):
            # Do Stuff

    """

    def __init__(self):
        self.registry = defaultdict(list)

    def on(self, hook):
        """Decorator function to add a new handler to the registry.

        Args:
            hook (HookType): Hook attribute for which to register the handler.

        Returns:
            callable: Decorator for registering listeners for the specified
            hook.

        """

        def decorator(handler):
            self.registry[hook].append(handler)

            return handler

        return decorator

    async def hook(self, hook, **kwargs):
        """Execute the list of handlers associated to the provided :class:`Hook`
        attribute.

        Args:
            hook (HookType): The hook attribute for which to execute handlers.

        """
        try:
            handlers = self.registry[hook]
        except KeyError:
            pass
        else:
            logger.debug("Running hook %s", hook)
            for handler in handlers:
                if iscoroutinefunction(handler):
                    await handler(**kwargs)
                else:
                    handler(**kwargs)


async def register_observer(controller, resource, start=True, **kwargs):
    """Create an observer for the given resource, and start it as a background task if
    wanted.

    If an observer already existed for this resource, it is stopped and deleted.

    Args:
        controller (Controller): the controller for which the observer will be
            added in the list of working observers.
        resource (krake.data.kubernetes.Application): the Application to observe or
        resource (krake.data.kubernetes.Cluster): the Cluster to observe.
        start (bool, optional): if False, does not start the observer as background
            task.

    """
    if resource.kind == Application.kind:
        cluster = await controller.kubernetes_api.read_cluster(
            namespace=resource.status.running_on.namespace,
            name=resource.status.running_on.name,
        )
        observer = KubernetesApplicationObserver(
            cluster,
            resource,
            controller.on_status_update,
            time_step=controller.observer_time_step,
        )

    elif resource.kind == Cluster.kind:
        observer = KubernetesClusterObserver(
            resource,
            controller.on_status_update,
            time_step=controller.observer_time_step,
        )
    else:
        logger.debug("Unknown resource kind. No observer was registered.", resource)
        return

    logger.debug(f"Start observer for {resource.kind} %r", resource.metadata.name)
    task = None
    if start:
        task = controller.loop.create_task(observer.run())

    controller.observers[resource.metadata.uid] = (observer, task)


async def unregister_observer(controller, resource, **kwargs):
    """Stop and delete the observer for the given resource. If no observer is started,
    do nothing.

    Args:
        controller (Controller): the controller for which the observer will be
            removed from the list of working observers.
        resource (krake.data.kubernetes.Application): the Application whose observer
        will be stopped or
        resource (krake.data.kubernetes.Cluster): the Cluster whose observer will be
        stopped.

    """
    if resource.metadata.uid not in controller.observers:
        return

    logger.debug(f"Stop observer for {resource.kind} {resource.metadata.name}")
    _, task = controller.observers.pop(resource.metadata.uid)
    task.cancel()

    try:
        with suppress(asyncio.CancelledError):
            await task
    except asyncio.TimeoutError:
        logger.debug("Observer timed out before being unregistered")
