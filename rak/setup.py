from setuptools import setup, find_packages


install_requires = []

setup(
    name="krake-rak",
    version="1.0.0",
    python_requires=">=3.6",
    description="CLI to install and manage a Krake setup",
    url="https://gitlab.com/rak-n-rok/krake",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    packages=find_packages(),
    install_requires=install_requires,
    extras_require={"test": {"dataclasses==0.6.*", "docker==4.*", "pytest==5.*"}},
)
