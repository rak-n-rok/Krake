import yaml
from pathlib import Path
from tempfile import TemporaryDirectory

from krake import load_config as load_krake_config


def load_config(config):
    with TemporaryDirectory() as tempdir:
        base_config_path = Path(tempdir) / "krake.yaml"

        with base_config_path.open("w") as fd:
            yaml.dump(config, stream=fd)
        config = load_krake_config(filepath=base_config_path)

    return config


def test_config_load_base(config):

    config_loaded = load_config(config)

    assert config_loaded == config


def test_config_overwrite(config, monkeypatch):
    monkeypatch.setenv("TLS_ENABLED", "true")
    config_loaded = load_config(config)

    assert config_loaded["tls"]["enabled"] is True


def test_config_prefix_restriction(config, monkeypatch):
    monkeypatch.setenv("DEFAULT-ROLES", "true")
    config_loaded = load_config(config)

    assert config_loaded["default-roles"] == config["default-roles"]


def test_config_empty_env_value(config, monkeypatch):
    monkeypatch.setenv("TLS_ENABLED", "")
    config_loaded = load_config(config)

    assert config_loaded["tls"]["enabled"] == config["tls"]["enabled"]


def test_config_underscore_param(config, monkeypatch):
    monkeypatch.setenv("AUTHENTICATION_ALLOW_ANONYMOUS", "false")
    config_loaded = load_config(config)

    assert config_loaded["authentication"]["allow_anonymous"] is False
