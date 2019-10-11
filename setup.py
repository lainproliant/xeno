from setuptools import setup, find_packages

from codecs import open
from os import path

here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, "README.md.rst"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="xeno",
    version="4.0.3",
    description="The Python dependency injector from outer space.",
    long_description=long_description,
    url="https://github.com/lainproliant/xeno",
    author="Lain Supe (lainproliant)",
    author_email="lainproliant@gmail.com",
    license="BSD",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "License :: OSI Approved :: BSD License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
    ],
    keywords="IOC dependency injector",
    packages=find_packages(),
    install_requires=[],
    extras_require={},
    package_data={'xeno': ['*.pyi', 'py.typed']},
    data_files=[],
    entry_points={"console_scripts": []},
)
