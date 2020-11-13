# API Generator

This is the documentation for the generator of the Krake code that depends on the API.
Its role is to generate automatically code that can be integrated into Krake's source
code.

For the moment, the following can be generated:

 * **API general definitions** from Krake's data files;
 * code for the **Krake API server side**, from the API definitions (mentioned above);
 * code for the **Krake API clients**, from the API definitions;
 * code for the **unit tests of the Krake API**, from the API definitions;
 * code for the **unit tests of the Krake API clients**, from the API definitions;

## Installation

This module does not belong to Krake, but the **Krake** package needs to be installed to
be able to start this module.

## Usage

All commands for this module process data from the Python module at the provided path.
It then returns the generated code to the standard output.

#### Basic Usage
Each element that can be created has its own generator. For each element of the list
above, these are the corresponding ones:

 * `api_definition`: API definition;
 * `api_client`: Krake API server side;
 * `api_server`: Krake API clients;
 * `test_client`: unit tests of the Krake API;
 * `test_server`: unit tests of the Krake API clients.

These names can then be used as `<generator>` in the following command:

```bash
python -m api_generator <generator> <parameters>
```

Each generator can have specific parameters.


#### API definitions

For the API definitions generator, the main parameter is the path to a data file from
Krake, which can be imported. By processing the resources in this file, a definition is
generated. The path should be given as packages separated by dots, with the file
extension being removed, for instance: `krake.data.core`.

To express if a resource is namespaced or not, a scope can be given to the generator. It
can be specified for a resource using the `--scopes` argument. A resource can have two
scopes:
 * `NAMESPACED`: it means the instances of the resource belongs to a specific namespace,
   and two resources with the same name can live in two different namespaces;
 * `NONE`: it means the instances of the resource is not bound to any namespace, and
   the instances have a unique name in Krake's whole database.


```bash
python -m api_generator api_definition <module_path_to_data_file> <options>

# Examples
python -m api_generator api_definition krake.data.kubernetes

python -m api_generator api_definition krake.data.core \
    --scopes Role=NONE --scopes RoleBinding=NONE \
    --scopes Metric=NONE --scopes MetricsProvider=NONE
```

The resulting file will contain an `ApiDef` instance, which contains a list of
`Resource` instance (for instance `Project` or `Cluster`). Each of these resources has a
list of `operation` instances (for instance `Create` or `Update`) which define how to
fetch information from the API, and the structure of the response that will be sent.


#### API and unit tests code

This section regroups the generators for the code of the API and unit tests, both for
the client and servers (so four generators in total).

The main parameter for these generators is the path to an API definition that can be
imported. This API definition can be one generated using the API definition generator,
or a custom one that follows the same syntax. By processing the resources in this file,
code can be generated for each one of their operations.

The path should be given as packages separated by dots, with the file extension being
removed, for instance: `api_generator.apidefs.core`.

The resources and operations processed and printed to stdout can be filtered, by using
respectively the `-r|--resource` and `-o|--operation` parameters. They can be used
several times. By default, all resources and operations are printed out.

```bash
python -m api_generator <api|test>_<client|server> <path_to_api_def> <parameters>

# Examples:
python -m api_generator test_client api_generator.apidefs.kubernetes

python -m api_generator api_server api_generator.apidefs.openstack \
    --resource project --operation read --operation update
```
