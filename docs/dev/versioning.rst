==========
Versioning
==========

In this chapter, the versioning schema for the Krake project will be explained.
Krake mainly tries to follow the Semantic Versioning in order to maintain a consistent scheme.

Single Source
=============

In order to have consistent versioning across all parts of the Krake project, a single source for
the version was introduced. This version will be retrieved by all modules, that need to access this
version number, as well as in ``pyproject.toml``, which provides the metadata for the PyPI package.

The version can be found in the ``__about__.py`` inside of the krake module, which also provides
other constant, global variables. This version can then be loaded into other (sub)modules by
importing this file.

Version update workflow
=======================

If a new version update shall be pushed out, should be decided by a majority of the active Krake team, and
not only a singular person. Whether to release a new version update should be decided by a majority of the
active Krake team, not just a single person; but a new version should still follow the SemVer recommendations
with respect to the previous version. The general workflow is shown in the following figure.

.. figure:: /img/version-update-workflow.drawio.png

After the team decides on a new version (which could happen after e.g. a milestone, a sprint or some
important patches), the current main is fetched and checked out.
From the main branch, a new branch is created, which follows the schema ``version-MAJOR.MINOR.PATCH``;
additional information like metadata, pre- or post-release versions should also be added.
In this branch, the version should be adapted inside the ``__about__.py``.
This change can then be committed and pushed to the origin repository, where a Merge Request should
be opened up. It should follow the naming schema ``Version MAJOR.MINOR.PATCH``. After a review by
fellow team members, this MR can be merged, while deleting its branch.
Then a new tag with the version ``MAJOR.MINOR.PATCH`` can be created inside the Gitlab UI, which should
trigger a new pipeline that generates a new PyPi package version as well as a new docker image.
Additional information should be added to this again, in order to maintain proper versioning.
