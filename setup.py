#!/usr/bin/env python

from setuptools import setup

with open("README.md", "r") as readme_file:
    long_description = readme_file.read()

setup(
    name="relations-redis",
    version="0.2.0",
    package_dir = {'': 'lib'},
    py_modules = [
        'relations_redis'
    ],
    install_requires=[
        'redis==3.5.2',
        'relations-dil>=0.6.14'
    ],
    url="https://github.com/relations-dil/python-relations-redis",
    author="Gaffer Fitch",
    author_email="relations@gaf3.com",
    description="DB/API Modeling for Redis",
    long_description=long_description,
    long_description_content_type="text/markdown",
    license_files=('LICENSE.txt',),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License"
    ]
)
