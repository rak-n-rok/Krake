==============
Gitlab CI/CD
==============

This part of the documentation describes test automation with `Gitlab CI/CD <https://docs.gitlab.com/ee/ci/>`_ as a framework by using the Openstack Infrastructure.
Therefore, the relationship between all files involved in the process is described below:

.. list-table::
    :widths: 40 90
    :header-rows: 1
    :stub-columns: 1

    * - File
      - Description

    * - `.gitlab-ci.yml  <https://gitlab.com/rak-n-rok/krake/-/blob/master/.gitlab-ci.yml?ref_type=heads>`_
      - Entry point for gitlab CI/CD to select the setup associated with a pipeline

    * - `ci/main-ci.yml <https://gitlab.com/rak-n-rok/krake/-/blob/master/ci/main-ci.yml?ref_type=heads>`_
      - Main setup of the pipeline used to invoke the test and release processes

    * - `ci/docker/ansible_runner/Dockerfile <https://gitlab.com/rak-n-rok/krake/-/blob/master/ci/docker/ansible_runner/Dockerfile?ref_type=heads>`_
      - Dockerfile used for building the custom CI/CD images

    * - `ci/cleanup-project.yml <https://gitlab.com/rak-n-rok/krake/-/blob/master/ci/cleanup-project.yml?ref_type=heads>`_
      - Scheduled pipeline that runs once a week to clean up the Openstack infrastructure

    * - `ci/build-ci-images.yml <https://gitlab.com/rak-n-rok/krake/-/blob/master/ci/build-ci-images.yml?ref_type=heads>`_
      - Setup for the scheduled build of the custom CI/CD images required by krake-ci-pipeline.yml



Pipeline Layout
====

The pipelines themselves are triggered in two ways. Either by commits and merge requests or by the creation of a scheduled pipeline.
The scheduling of the pipelines can be configured here: `pipeline_schedules <https://gitlab.com/rak-n-rok/krake/-/pipeline_schedules>`_


.. list-table:: scheduled pipelines:
    :widths: 40 10 80
    :header-rows: 1
    :stub-columns: 1

    * - Schedule
      - Time of execution
      - Description

    * - **build ci images**
      - Daily 2 am before *Master Night Run*
      - Build CI images used in *krake-ci-pipeline.yml* on a daily basis

    * - **Master Night Run**
      - Daily 4 am  after *build ci images*
      - Invokes *krake-ci-pipeline.yml* on daily bases

    * - **cleanup OpenStack project**
      - Sunday 3 am
      - Cleanup of e2e test artifacts if previous CI jobs were not successfully cleaned up


The following figure shows the order in which the individual pipelines are to be executed.

.. uml::

  @startuml
  'Title krake-ci-pipline.yaml pipeline layout


  state "**build-ci-images.yml**" as build_ci_images {
    state "build-ci-images" as build {
    }
  }


  state "**cleanup_krake_os_project.yml**" as cleanup_krake_os_project {
    state "e2e-os-project-cleanup" as os_project_cleanup {
    }
  }


  state "**krake-ci-pipeline.yml**" as krake_ci_pipeline {
  state "**stage: Test**" as stage_test {
    State  "unittest-krake-3.X" as ux {

    }
    ||
    State  "e2e-provisioning" as e2e_prov {
    }
  }
  state "**stage: e2e**" as stage_e2e {
    State  "coverage" as cov {
    }
    ||
    State  "e2e-test-apps" as e2e_app {
    }
    ||
    State  "e2e-test-im" as e2e_im {
    }
  }

  state "**stage: release**" as stage_rel {
    State  "e2e-cleanup" as clean #lightgreen ##[bold]green{
    }
    ||
    State  "pypi" as pypi #lightblue ##[dashed]blue {

    }
    ||
    State  "docker" as docker #lightblue ##[dashed]blue{

    }
  }
  stage_test -right-> stage_e2e
  stage_e2e -right-> stage_rel
  }

  build_ci_images -down-> krake_ci_pipeline
  krake_ci_pipeline -down->  cleanup_krake_os_project

  @enduml


.. note::
  If there are changes to the CI runner setup, they must first be pushed
  to the master branch so they can get built into the Docker images used
  by Gitlab CI/CD for testing.
  The build-ci-images pipeline is then automatically triggered as specified in
  `pipeline_schedules <https://gitlab.com/rak-n-rok/krake/-/pipeline_schedules>`_.
  In addition, the scheduled build pipeline can also be triggered manually.


In the following there are detailed behavioral descriptions of the CI jobs
triggered by `krake-ci-pipeline.yml`. Those represent the way to be used on
daily based developement. In Order to contribute to Krake, a developer must
first create an issue with a corresponding branch to which he can upload commits.
Uploading to a branch triggers only the unit tests. However, if the changes are
sufficient to be merged, a developer can create a merge request.
This creates a merge request branch that triggers the e2e tests. In addition,
this pipeline is also triggered daily for the master pipeline.


Regular branches pipeline
^^^^^^^^^

The following image shows the behavior for regular branches without an existing MR.

.. uml::

  'Title krake-ci-pipline.yaml executed for regular branches

  state "**stage: Test**" as stage_test {
    State  "unittest-krake-3.X" as ux {

    }

    State  "e2e-provisioning" as e2e_prov {

    }
    e2e_prov: skipped
  }


  state "**stage: e2e**" as stage_e2e {

    State  "coverage" as cov {

    }

    State  "e2e-test-apps" as e2e_app {

    }
    e2e_app: skipped
    State  "e2e-test-im" as e2e_im {

    }
    e2e_im: skipped
  }

  stage_test -down[hidden]-> stage_e2e
  ux -down-> cov: on success
  @enduml

Master and Merge Request pipeline
^^^^^^^^^

Following image shows the behavior on branches with an excisting MR.
In addition, this pipeline also runs for the daily tests of the master branch.

.. uml::

  @startuml
  'Title krake-ci-pipline.yaml executed for master and merge requests

  state "**stage: Test**" as stage_test {
    State  "unittest-krake-3.X" as ux {

    }

    State  "e2e-provisioning" as e2e_prov {

    }

  }


  state "**stage: e2e**" as stage_e2e {

    State  "coverage" as cov {

    }

    State  "e2e-test-apps" as e2e_app {

    }

    State  "e2e-test-im" as e2e_im {

    }

  }

  state "**stage: release**" as stage_rel {

    State  "pypi" as pypi #lightblue ##[dashed]blue {

    }

    State  "docker" as docker #lightblue ##[dashed]blue{

    }
    docker: skipped
    pypi: skipped
    State  "e2e-cleanup" as clean #lightgreen ##[bold]green{

    }

  }

  stage_test -down[hidden]-> stage_e2e
  stage_e2e -down[hidden]-> stage_rel

  e2e_prov -down-> e2e_app: on success
  e2e_prov -down-> e2e_im: on success
  ux -down-> cov: on success
  stage_e2e -down-> clean :allways
  @enduml


Release pipeline
^^^^^^^^^

The following figure shows the behavior for releases triggered by the creation
of a tag in Gitlab to signal a new version.

.. uml::

  @startuml
  'Title krake-ci-pipline.yaml executed for release branches

  state "**stage: Test**" as stage_test {
    State  "unittest-krake-3.X" as ux {

    }

    State  "e2e-provisioning" as e2e_prov {

    }
    'e2e_prov: skipped
  }


  state "**stage: e2e**" as stage_e2e {

    State  "coverage" as cov {

    }

    State  "e2e-test-apps" as e2e_app {

    }

    State  "e2e-test-im" as e2e_im {

    }
    'e2e_app: skipped
    'e2e_im: skipped
  }

  state "**stage: release**" as stage_rel {

    State  "pypi" as pypi #lightblue ##[dashed]blue {

    }

    State  "docker" as docker #lightblue ##[dashed]blue{

    }

    State  "e2e-cleanup" as clean #lightgreen ##[bold]green{

    }
    'docker: skipped
    'pypi: skipped
    'clean: skipped

    clean  -right[hidden]-> docker
    docker -right[hidden]-> pypi

  }

  state fork1 <<fork>>

  stage_test -down[hidden]-> stage_e2e
  stage_e2e -down[hidden]-> stage_rel

  e2e_prov -down-> e2e_app: on success
  e2e_prov -down-> e2e_im: on success
  ux -down-> cov: on success

  stage_e2e -down-> clean :allways

  stage_e2e -down-> fork1: on success
  fork1 -down-> docker
  fork1 -down-> pypi

  @enduml



Pipeline Configuration/Maintanance
=====

The current CI/CD configuration of Gitlab does not allow to run in one single
operation. More precisely, the images used for testing are not build by
issue branches. The only way to create and test the images during development is
to do it manually and upload them to the container registers.
However, remember that the images are overwritten daily by the schedule
*ci-images-build** pipeline.
In order to update and modify the software tools used in the CI pipeline, you
can modify the following file: `ci/docker/ansible_runner/Dockerfile <https://gitlab.com/rak-n-rok/krake/-/blob/master/ci/docker/ansible_runner/Dockerfile?ref_type=heads>`_
