#!/usr/bin/env python3
"""Packaging setup for Atenea."""
from setuptools import setup, find_packages

setup(
    name="atenea",
    version="0.1.0",
    description="Atenea — AI personal assistant",
    packages=find_packages(exclude=["tests", "scripts", "data", "docs"]),
    include_package_data=True,
    python_requires=">=3.11",
)
