from setuptools import setup, find_packages


install_requires = ["requests", "texttable", "python-dateutil"]

setup(
    name="rok",
    version="1.0.0",
    python_requires=">=3.6",
    packages=find_packages(),
    install_requires=install_requires,
    extras_require={"dev": {"pytest", "responses"}},
    entry_points={"console_scripts": ["rok=rok.__main__:main"]},
)
