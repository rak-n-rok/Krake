from pathlib import Path
from setuptools import setup, find_packages


BASEDIR = Path(__file__).parent.absolute()


def read(rel_path):
    with open(Path(BASEDIR, rel_path)) as stream:
        return stream.read()


def get_version(rel_path):
    for line in read(rel_path).splitlines():
        if line.startswith("__version__"):
            delim = '"' if '"' in line else "'"
            return line.split(delim)[1]
    else:
        raise RuntimeError("Unable to find version string.")


def read_requirements(requirements_file):
    contents = read(requirements_file)
    return [
        line
        for line in contents.splitlines()
        if line.strip() and not line.startswith("#")
    ]


setup(
    name="krake",
    version=get_version("krake/__about__.py"),
    description="",
    url="https://gitlab.com/rak-n-rok/krake",
    maintainer="Krake Development Team",
    maintainer_email="krake@cloudandheat.com",
    python_requires=">=3.8",
    packages=find_packages(),
    install_requires=read_requirements("requirements/main.in"),
    extras_require={
        "dev": read_requirements("requirements/dev.in"),
        "ansible": read_requirements("requirements/ansible.in"),
        "api_generator": read_requirements("requirements/api_generator.in"),
    },
    scripts=[
        "scripts/krake_bootstrap_db",
        "scripts/krake_generate_config",
    ],
)
