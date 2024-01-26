# TODO: class InfrastructureClusterObserver(Observer):
#
#     TODO: async def poll_resource(self):
#        get the right infrastructure manager
#        create infrastructure manager client
#        query infrastructure manager API
#        gather information in ClusterNode objects
#            Either create a new InfrastructureClusterNode object (preferred) or use the existing KubernetesClusterNode one
#       return gathered status

# TODO: async def register_observer(controller, resource, start=True, **kwargs):
#    if resource.kind == Cluster.kind:
#        observer = InfrastructureClusterObserver(
#            resource=resource,
#            on_res_update=controller.on_status_update,
#            time_step=controller.observer_time_step,
#        )
#
#    task = create_task(observer.run())
#    controller.observers[resource.metadata.uid] = (observer, task)
