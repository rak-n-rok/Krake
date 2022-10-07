from setuptools import setup, find_packages


install_requires = [
    "PyYAML==5.*",
    "python-dateutil==2.*",
    "requests==2.*",
    "texttable==1.*",
    "requests-toolbelt==0.9.*",
]

setup(
    name="rok",
    version="1.0.0",
    python_requires=">=3.7",
    packages=find_packages(),
    install_requires=install_requires,
    entry_points={"console_scripts": ["rok=rok.__main__:main"]},
)
