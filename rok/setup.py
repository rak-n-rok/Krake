from setuptools import setup, find_packages


install_requires = [
    "PyYAML==5.*",
    "python-dateutil==2.*",
    "requests==2.*",
    "texttable==1.*",
]

setup(
    name="rok",
    version="1.0.0",
    description="CLI for Krake",
    url="https://gitlab.com/rak-n-rok/krake",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
    packages=find_packages(),
    install_requires=install_requires,
    entry_points={"console_scripts": ["rok=rok.__main__:main"]},
)
