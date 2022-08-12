=============================
Kubernetes Cluster Controller
=============================
The Kubernetes Cluster Controller manages and monitors Kubernetes clusters registered in
Krake. To do this for each Kubernetes cluster registered in Krake, an observer is
created. This observer directly calls the Kubernetes API of the specific cluster and
checks on its current state. The Kubernetes cluster controller then updates the
internally stored state of the registered Kubernetes cluster according to the response
from the Kubernetes cluster observer.

The Kubernetes Cluster Controller is launched separately.

.. note::

  Since this is a relatively new implementation, the Kubernetes
  Cluster Controller will certainly be extended by
  additional features and functionalities in the future.

For more information on what the Kubernetes Cluster Observer
does and what features it offers, see
:ref:`dev/observers:Kubernetes Cluster Observer`.



