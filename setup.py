#!/usr/bin/env python
"""
A setup script
"""

import json
from setuptools import setup, find_packages
from mpds_aiida_workflows import __version__

if __name__ == '__main__':
    # Provide static information in setup.json
    # such that it can be discovered automatically
    with open('setup.json', 'r') as info:
        kwargs = json.load(info)
    setup(
        packages=find_packages(),
        version=__version__,
        # long_description=open('README.md').read(),
        # long_description_content_type='text/markdown',
        **kwargs)
