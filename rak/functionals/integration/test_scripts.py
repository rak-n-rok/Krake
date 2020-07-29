"""This module defines E2e integration tests for the Krake scripts."""
import copy
import yaml
import os
import tarfile

import docker
from pathlib import Path
from tempfile import TemporaryDirectory
from utils import run, check_return_code

client = docker.from_env()

TEST_CONFIG = {
    "static_value": "value",
    "etcd": {"host": "$etcd_host", "port": "$etcd_port"},
    "tls": {
        "enabled": "$tls_enabled",
        "cert": "$cert_dir/test.cert",
        "key": "$cert_dir/test.key",
    },
    "api_endpoint": "$api_endpoint",
    "worker_count": "$worker_count",
    "debounce": "$debounce",
    "reschedule_after": "$reschedule_after",
    "stickiness": "$stickiness",
}


def copy_to_container(container, srcs, dst):
    """Copy the file to the specific directory in the docker container

    Args:
        container (docker.models.containers.Container): Container where the file will
            be stored
        srcs (List[Path]): Paths list of the source files
        dst (Path): Path to the destination directory where the files will
            be stored

    """
    for src in srcs:
        os.chdir(src.parent)
        with tarfile.open(src.with_suffix(".tar"), mode="w") as tar:
            tar.add(src.name)

        with open(src.with_suffix(".tar"), "rb") as f:
            data = f.read()

        container.put_archive(str(dst), data)


def exec_container(container, cmd, suppress=False):
    """Execute command in the docker container

    Args:
        container (docker.models.containers.Container): Container where the command will
            be executed
        cmd (list): Command to be executed
        suppress (bool): If True, exception is suppressed. Defaults to False

    Raises:
        docker.errors.ContainerError: If non-zero exit code

    """
    exit_code, output = container.exec_run(cmd)
    if exit_code and not suppress:
        raise docker.errors.ContainerError(
            container, exit_code, cmd, container.name, ""
        )
    return output


def test_generate(krake_container):
    """Basic end to end testing for ``krake_generate_config`` script

    E2e testing of ``krake_generate_config`` script is executed against
    Krake docker test infrastructure.

    We run a basic workflow in following steps:
    1. Create a test.config.yaml.template file
    2. Copy test.config.yaml.template file to the Krake docker container
    3. Execute krake_generate_config script
    4. Validate generated test.config.yaml file
    5. Delete the test.config.yaml.template file and generated test.config.yaml
    file from the Krake container

    Args:
        krake_container (str): Krake container name

    """

    krake = client.containers.get(krake_container)

    dst = Path("/home/krake")
    config = str(dst / "test.config.yaml")
    template = str(dst / "test.config.yaml.template")

    config_vars = [
        "--tls-enabled",
        "--cert-dir",
        "test_dir",
        "--api-host",
        "1.1.1.1",
        "--api-port",
        "1111",
        "--etcd-host",
        "2.2.2.2",
        "--etcd-port",
        "2222",
        "--worker-count",
        "10",
        "--debounce",
        "10",
        "--reschedule-after",
        "10",
        "--stickiness",
        "10",
    ]

    # 1. Create a test.config.yaml.template file
    with TemporaryDirectory() as tempdir:
        template_tmp_path = Path(tempdir) / "test.config.yaml.template"
        with open(template_tmp_path, "w") as file:
            yaml.dump(TEST_CONFIG, stream=file)
        # 2. Copy test.config.yaml.template file to the Krake docker container
        copy_to_container(krake, [template_tmp_path], dst)

    # 3. Execute generate script
    exec_container(
        krake, ["krake_generate_config", template, "--dst", str(dst)] + config_vars
    )

    # 4. Validate generated test.config.yaml file
    out = exec_container(krake, ["cat", config])
    assert yaml.safe_load(out) == {
        "static_value": "value",
        "etcd": {"host": "2.2.2.2", "port": 2222},
        "tls": {
            "enabled": True,
            "cert": "test_dir/test.cert",
            "key": "test_dir/test.key",
        },
        "api_endpoint": "https://1.1.1.1:1111",
        "worker_count": 10,
        "debounce": 10,
        "reschedule_after": 10,
        "stickiness": 10,
    }

    # 5. Delete the test.config.yaml.template file and generated test.config.yaml
    # file from the Krake container
    exec_container(krake, ["rm", config, template])


TEST_BOOTSTRAP = {
    "api": "core",
    "kind": "Metric",
    "metadata": {"name": "test"},
    "spec": {
        "max": "5.0",
        "min": "4.0",
        "provider": {"metric": "test", "name": "test"},
    },
}


def test_bootstrap(krake_container, etcd_container, etcd_container_port):
    """Basic end to end testing for ``krake_bootstrap_db`` script

    E2e testing of ``krake_bootstrap_db`` script is executed against
    Krake docker test infrastructure.

    We run a basic workflow in following steps:
    1. Create a bootstrap.yaml file
    2. Copy bootstrap.yaml file to the Krake docker container
    3. Execute krake_bootstrap_db script
    4. Validate Etcd database
    5. Execute krake_bootstrap_db script with the `force` option
    6. Validate Etcd database
    7. Delete the bootstrap.yaml file from the Krake container and test record
    from the Etcd database

    Args:
        krake_container (str): Krake container name
        etcd_container (str): Etcd container name
        etcd_container_port (str): Etcd container port

    """

    krake = client.containers.get(krake_container)
    etcd = client.containers.get(etcd_container)
    record_name = TEST_BOOTSTRAP["metadata"]["name"]
    record_path = "/core/metric/" + record_name

    bootstrap_cmd = [
        "krake_bootstrap_db",
        "--db-host",
        etcd_container,
        "--db-port",
        etcd_container_port,
    ]

    dst = Path("/home/krake")
    bootstrap = str(dst / "bootstrap.yaml")

    # 1. Create a bootstrap.yaml file
    with TemporaryDirectory() as tempdir:
        bootstrap_file = Path(tempdir) / "bootstrap.yaml"
        with open(bootstrap_file, "w") as file:
            yaml.dump(TEST_BOOTSTRAP, stream=file)
        # 2. Copy bootstrap.yaml file to the Krake docker container
        copy_to_container(krake, [bootstrap_file], dst)

    # Ensure the test record does not exist in the database
    exec_container(etcd, ["etcdctl", "del", record_path])

    # 3. Execute bootstrap script
    exec_container(krake, bootstrap_cmd + [bootstrap])

    # 4. Validate Etcd database
    out = exec_container(etcd, ["etcdctl", "get", "--print-value-only", record_path])
    assert yaml.safe_load(out)["metadata"]["name"] == record_name

    # 5. Execute bootstrap script with the `force` option
    exec_container(krake, bootstrap_cmd + ["--force", bootstrap])

    # 6. Validate Etcd database
    out = exec_container(etcd, ["etcdctl", "get", "--print-value-only", record_path])
    assert yaml.safe_load(out)["metadata"]["name"] == record_name

    # 7. Delete the bootstrap.yaml file from the Krake container and test record
    # from the Etcd database
    exec_container(etcd, ["etcdctl", "del", record_path])
    exec_container(krake, ["rm", bootstrap])


def test_bootstrap_from_stdin(krake_container, etcd_container, etcd_container_port):
    """End to end testing for ``krake_bootstrap_db`` script, reading from stdin

    E2e testing of ``krake_bootstrap_db`` script is executed against
    Krake docker test infrastructure.

    We run a basic workflow in following steps:
    1. Execute krake_bootstrap_db script, reading file from stdin
    2. Validate Etcd database
    3. Execute krake_bootstrap_db script with the `force` option
    4. Validate Etcd database
    5. Delete the test record from the Etcd database

    Args:
        krake_container (str): Krake container name
        etcd_container (str): Etcd container name
        etcd_container_port (str): Etcd container port

    """
    etcd = client.containers.get(etcd_container)
    record_name = TEST_BOOTSTRAP["metadata"]["name"]
    record_path = "/core/metric/" + record_name

    bootstrap_cmd = [
        "docker",
        "exec",
        "-i",
        krake_container,
        "krake_bootstrap_db",
        "--db-host",
        etcd_container,
        "--db-port",
        etcd_container_port,
        "-",
    ]
    bootstrap_file = yaml.dump(TEST_BOOTSTRAP).encode("utf-8")

    # Ensure the test record does not exist in the database
    exec_container(etcd, ["etcdctl", "del", record_path])

    # 1. Execute bootstrap script
    error_message = "The bootstrapping through stdin failed."
    run(
        bootstrap_cmd,
        retry=0,
        condition=check_return_code(error_message),
        input=bootstrap_file,
    )

    # 2. Validate Etcd database
    out = exec_container(etcd, ["etcdctl", "get", "--print-value-only", record_path])
    assert yaml.safe_load(out)["metadata"]["name"] == record_name

    # 3. Execute bootstrap script with the `force` option
    bootstrap_cmd.insert(-1, "--force")
    error_message = "The bootstrapping through stdin failed when using '--force'."
    run(
        bootstrap_cmd,
        retry=0,
        condition=check_return_code(error_message),
        input=bootstrap_file,
    )

    # 4. Validate Etcd database
    out = exec_container(etcd, ["etcdctl", "get", "--print-value-only", record_path])
    assert yaml.safe_load(out)["metadata"]["name"] == record_name

    # 5. Delete the test record from the Etcd database
    exec_container(etcd, ["etcdctl", "del", record_path])


TEST_BOOTSTRAP_INVALID = {
    "api": "core",
    "kind": "INVALID",
    "metadata": {"name": "test_invalid"},
    "spec": {
        "max": "5.0",
        "min": "4.0",
        "provider": {"metric": "test_invalid", "name": "test_invalid"},
    },
}


def test_bootstrap_rollback_invalid(
    krake_container, etcd_container, etcd_container_port
):
    """Basic rollback end to end testing of the ``krake_bootstrap_db`` script.

    Rollback scenario with the invalid resource.

    E2e rollback testing of the ``krake_bootstrap_db`` script is executed against
    Krake docker test infrastructure.

    We test the rollback as follows:
    1. Create a bootstrap.yaml file that contains the valid resource
       Create a bootstrap_invalid.yaml file that contains the invalid resource syntax
    2. Copy bootstrap.yaml and bootstrap_invalid.yaml files to the Krake
       docker container
    3. Execute krake_bootstrap_db script
    4. Validate Etcd database, the database should not store any of the two
       resources if the rollback passed
    5. Delete the bootstrap.yaml and bootstrap_invalid.yaml files from the Krake
       container

    Args:
        krake_container (str): Krake container name
        etcd_container (str): Etcd container name
        etcd_container_port (str): Etcd container port

    """

    krake = client.containers.get(krake_container)
    etcd = client.containers.get(etcd_container)
    record_paths = (
        "/core/metric/" + TEST_BOOTSTRAP["metadata"]["name"],
        "/core/metric/" + TEST_BOOTSTRAP_INVALID["metadata"]["name"],
    )

    bootstrap_cmd = [
        "krake_bootstrap_db",
        "--db-host",
        etcd_container,
        "--db-port",
        etcd_container_port,
    ]

    dst = Path("/home/krake")
    bootstrap = str(dst / "bootstrap.yaml")
    bootstrap_invalid = str(dst / "bootstrap_invalid.yaml")

    # 1. Create a bootstrap.yaml file that contains the valid resource
    #    Create a bootstrap_invalid.yaml file that contains the invalid resource syntax
    with TemporaryDirectory() as tempdir:
        bootstrap_file = Path(tempdir) / "bootstrap.yaml"
        bootstrap_invalid_file = Path(tempdir) / "bootstrap_invalid.yaml"
        with open(bootstrap_file, "w") as file:
            yaml.dump(TEST_BOOTSTRAP, stream=file)
        with open(bootstrap_invalid_file, "w") as file:
            yaml.dump(TEST_BOOTSTRAP_INVALID, stream=file)
        # 2. Copy bootstrap.yaml and bootstrap_invalid.yaml files to the Krake
        #    docker container
        copy_to_container(krake, [bootstrap_file, bootstrap_invalid_file], dst)

    # Ensure the test records do not exist in the database
    for record_path in record_paths:
        exec_container(etcd, ["etcdctl", "del", record_path])

    # 3. Execute krake_bootstrap_db script
    #    krake_bootstrap_db script returns non-zero return code, if invalid input
    out = exec_container(
        krake, bootstrap_cmd + [bootstrap, bootstrap_invalid], suppress=True
    )
    assert "The kind 'INVALID' could not be found." in out.decode("unicode-escape")
    assert "Rollback to previous state has been performed" in out.decode(
        "unicode-escape"
    )

    # 4. Validate Etcd database, the database should not store any of the two
    #    resources if the rollback passed
    for record_path in record_paths:
        out = exec_container(
            etcd, ["etcdctl", "get", "--print-value-only", record_path]
        )
        assert not out

    # 5. Delete the bootstrap.yaml and bootstrap_invalid.yaml files from the Krake
    #    container
    exec_container(krake, ["rm", bootstrap])
    exec_container(krake, ["rm", bootstrap_invalid])


TEST_BOOTSTRAP_PRESENT = {
    "api": "core",
    "kind": "Metric",
    "metadata": {"name": "test_present"},
    "spec": {
        "max": "5.0",
        "min": "4.0",
        "provider": {"metric": "test_present", "name": "test_present"},
    },
}


def test_bootstrap_rollback_present(
    krake_container, etcd_container, etcd_container_port
):
    """Basic rollback end to end testing of the ``krake_bootstrap_db`` script.

    Rollback scenario with the already present resource.

    E2e rollback testing of the ``krake_bootstrap_db`` script is executed against
    Krake docker test infrastructure.

    We test the rollback as follows:
    1. Create a bootstrap.yaml file that contains the valid resource
       Create a bootstrap_present.yaml file that contains the valid resource
    2. Copy bootstrap.yaml and bootstrap_present.yaml files to the Krake
       docker container
    3. Execute krake_bootstrap_db script only using the bootstrap_present.yaml file
    4. Validate Etcd database, the database should store record defined in the
       bootstrap_present.yaml file
    5. Modify the content of bootstrap_present.yaml
    6. Copy updated bootstrap_present.yaml files to the Krake
       docker container
    7. Execute krake_bootstrap_db script using both files
    8. Validate Etcd database, the database should keep its previous state
       and the record defined in the bootstrap.yaml file should not be inserted
    9. Delete the bootstrap.yaml and bootstrap_present.yaml files from the Krake
       container and test_present record from the Etcd database

    Args:
        krake_container (str): Krake container name
        etcd_container (str): Etcd container name
        etcd_container_port (str): Etcd container port

    """
    krake = client.containers.get(krake_container)
    etcd = client.containers.get(etcd_container)
    record_paths = (
        "/core/metric/" + TEST_BOOTSTRAP["metadata"]["name"],
        "/core/metric/" + TEST_BOOTSTRAP_PRESENT["metadata"]["name"],
    )

    bootstrap_cmd = [
        "krake_bootstrap_db",
        "--db-host",
        etcd_container,
        "--db-port",
        etcd_container_port,
    ]

    dst = Path("/home/krake")
    bootstrap = str(dst / "bootstrap.yaml")
    bootstrap_present = str(dst / "bootstrap_present.yaml")

    # 1. Create a bootstrap.yaml file that contains the valid resource
    #    Create a bootstrap_present.yaml file that contains the valid resource
    with TemporaryDirectory() as tempdir:
        bootstrap_file = Path(tempdir) / "bootstrap.yaml"
        bootstrap_present_file = Path(tempdir) / "bootstrap_present.yaml"
        with open(bootstrap_file, "w") as file:
            yaml.dump(TEST_BOOTSTRAP, stream=file)
        with open(bootstrap_present_file, "w") as file:
            yaml.dump(TEST_BOOTSTRAP_PRESENT, stream=file)
        # 2. Copy bootstrap.yaml and bootstrap_present.yaml files to the Krake
        #    docker container
        copy_to_container(krake, [bootstrap_file, bootstrap_present_file], dst)

    # Ensure the test records do not exist in the database
    for record_path in record_paths:
        exec_container(etcd, ["etcdctl", "del", record_path])

    # 3. Execute krake_bootstrap_db script only using the bootstrap_present.yaml file
    exec_container(krake, bootstrap_cmd + [bootstrap_present])

    # 4. Validate Etcd database, the database should store record defined in the
    #    bootstrap_present.yaml file
    for record_path in record_paths:
        out = exec_container(
            etcd, ["etcdctl", "get", "--print-value-only", record_path]
        )
        if TEST_BOOTSTRAP_PRESENT["metadata"]["name"] in record_path:
            assert (
                yaml.safe_load(out)["metadata"]["name"]
                == TEST_BOOTSTRAP_PRESENT["metadata"]["name"]
            )
        else:
            assert not out

    # 5. Modify the content of bootstrap_present.yaml
    test_bootstrap_present_updated = copy.deepcopy(TEST_BOOTSTRAP_PRESENT)
    test_bootstrap_present_updated["spec"]["provider"] = {
        "metric": "test_present_updated",
        "name": "test_present_updated",
    }
    with TemporaryDirectory() as tempdir:
        bootstrap_present_file = Path(tempdir) / "bootstrap_present.yaml"
        with open(bootstrap_present_file, "w") as file:
            yaml.dump(test_bootstrap_present_updated, stream=file)
        # 6. Copy updated bootstrap_present.yaml files to the Krake
        #    docker container
        copy_to_container(krake, [bootstrap_present_file], dst)

    # 7. Execute krake_bootstrap_db script using both files
    #    krake_bootstrap_db script returns non-zero return code,
    #    if the resource already present in the database
    out = exec_container(
        krake, bootstrap_cmd + [bootstrap, bootstrap_present], suppress=True
    )
    assert "Resource already present in database" in out.decode("unicode-escape")
    assert "Rollback to previous state has been performed" in out.decode(
        "unicode-escape"
    )

    # 8. Validate Etcd database, the database should keep its previous state
    #    and the record defined in the bootstrap.yaml file should not be inserted
    for record_path in record_paths:
        out = exec_container(
            etcd, ["etcdctl", "get", "--print-value-only", record_path]
        )
        if TEST_BOOTSTRAP_PRESENT["metadata"]["name"] in record_path:
            assert (
                yaml.safe_load(out)["metadata"]["name"]
                == TEST_BOOTSTRAP_PRESENT["metadata"]["name"]
            )
            assert (
                yaml.safe_load(out)["spec"]["provider"]
                == TEST_BOOTSTRAP_PRESENT["spec"]["provider"]
            )
        else:
            assert not out

    # 9. Delete the bootstrap.yaml and bootstrap_present.yaml files from the Krake
    #    container and test_present record from the Etcd database
    exec_container(
        etcd,
        [
            "etcdctl",
            "del",
            "/core/metric/" + TEST_BOOTSTRAP_PRESENT["metadata"]["name"],
        ],
    )
    exec_container(krake, ["rm", bootstrap])
    exec_container(krake, ["rm", bootstrap_present])
