from setuptools import setup, find_packages


install_requires = []

setup(
    name="rak",
    version="1.0.0",
    packages=find_packages(),
    install_requires=install_requires,
    extras_require={
        "test": {
            "dataclasses",
            "pytest",
            "testinfra",
            "openstacksdk",
            "ansible==2.7.10",
        }
    },
)
