from setuptools import setup, find_packages


install_requires = []

setup(
    name="rak",
    version="1.0.0",
    packages=find_packages(),
    install_requires=install_requires,
    extras_require={
        "test": {
            "dataclasses==0.6.*",
            "docker==4.*",
            "pytest==6.*",
            "pytest-timeout",
            "minio"
        }
    },
)
