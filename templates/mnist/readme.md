# MNIST Training

The MNIST database (Modified National Institute of Standards and Technology database) is
a large database of handwritten digits that is commonly used for training various image
processing systems. In our case, we use an example training on an MNIST dataset to test
the handling of a stateful application by Krake.

The example is especially useful to test
 - shutdown hook
 - complete hook

since both situations appear in this application.
If an application gets rescheduled due to a change in the cluster infrastructure, the
shutdown hook is triggered, which stops the application and saves the current results
into an external Minio bucket.
If the application finishes it's training, the complete hook is activated, which tells
Krake that the application is done.


This folder contains all necessary files to create your own Docker image of this
application and possibly modify it to your needs as well as the necessary YAML and
Python files to create the application with Krake and integrate a shutdown hook script.
