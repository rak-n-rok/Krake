from setuptools import setup, find_packages


install_requires = ["python-dateutil==2.*", "requests==2.*", "texttable==1.*"]

setup(
    name="rok",
    version="1.0.0",
    python_requires=">=3.6",
    packages=find_packages(),
    install_requires=install_requires,
    entry_points={"console_scripts": ["rok=rok.__main__:main"]},
)
