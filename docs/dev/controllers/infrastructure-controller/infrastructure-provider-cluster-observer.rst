========================================
Infrastructure Provider Cluster Observer
========================================

Krake constantly observes the status of the clusters it created
via an infrastructure provider.
For each one of these clusters a separate infrastructure provider cluster observer is created.

This specific observer connects to the respective infrastructure provider API
depending on the type of cloud in which the cluster was created.
It uses a generic infrastructure provider client
to periodically fetch the real world state of the clusters.
The fetched state of each cluster is transferred into the database of Krake
whenever a difference between real world and database is detected.


.. note::

    More to be documented.
