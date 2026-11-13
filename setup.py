from setuptools import setup, find_packages

setup(
    name="econ-harness",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "pyyaml>=6.0",
        "click>=8.0",
        "aiosqlite>=0.19",
    ],
    entry_points={
        "console_scripts": [
            "econ-harness=econ_harness.__main__:cli",
        ],
    },
)
