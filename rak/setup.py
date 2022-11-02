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
            "minio",
            "Werkzeug==2.1.*",
            # jinja2 imports `soft_unicode` from markupsafe library.
            # `soft_unicode` was removed in markupsafe==2.1.0.
            "markupsafe==2.0.1",
            "pytest-httpserver==1.*",
        }
    },
)
